#!/usr/bin/env python3
"""Sora DB — SSH 経由で sqlplus/mysql/psql 等を実行する独立 DB ツール

Sora Editor / Multi-Server Log Viewer と同じ接続プロファイル
(~/.ssh_log_viewer_profiles.json) を共有する。 起動引数:
    sora_db.exe [--profile NAME] [--query "SELECT ..."]
で他アプリ (Sora / LogViewer) から SQL を直接送って実行できる。
"""
__version__ = "0.1.0"

import sys
import os
import json
import argparse

from PyQt6.QtCore import Qt, pyqtSignal, QThread, QSize
import re
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QPlainTextEdit, QPushButton, QLabel, QComboBox, QStatusBar, QStackedWidget,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QSpinBox, QMessageBox, QFileDialog,
)
from PyQt6.QtGui import (
    QFont, QAction, QKeySequence, QColor,
)


# ---------------------------------------------------------------------------
# 接続プロファイル (LogViewer / Sora と共通) と DB コマンドテンプレ
# ---------------------------------------------------------------------------
_DB_PROFILES_PATH = os.path.join(
    os.path.expanduser('~'), '.ssh_log_viewer_profiles.json',
)
_SORA_DB_HISTORY_PATH = os.path.join(
    os.path.expanduser('~'), '.sora_db_history.json',
)

_DB_CMD_PRESETS = {
    "Oracle (sqlplus)": (
        "sqlplus -S USER/PASS@SID <<'EOF'\n"
        "set sqlblanklines on define off\n"
        "set markup csv on quote on\n"
        "set feedback off pagesize 0 trimspool on\n"
        "{SQL};\n"
        "exit\nEOF"
    ),
    "MySQL/MariaDB":  'mysql -u USER -pPASS -h localhost DBNAME -e "{SQL}"',
    "PostgreSQL":     'PGPASSWORD=PASS psql -h localhost -U USER -d DBNAME -c "{SQL}"',
    "SQLite":         'sqlite3 /path/to/db.sqlite "{SQL}"',
    "SQL Server (sqlcmd)": 'sqlcmd -S localhost -U USER -P PASS -d DBNAME -Q "{SQL}"',
}


def _clean_sqlplus_output(text: str) -> str:
    """SQL*Plus 出力からクエリ結果だけを抽出する (text_editor 側と同実装)。
    - 起動バナー (SQL*Plus Release / Copyright / Connected to: 等) を除去
    - 行頭 `SQL>` プロンプトと multi-line 継続プロンプトを除去
    - `Disconnected from Oracle ...` 以降の終了メッセージを除去
    - sqlplus 系出力でなければ無加工で返す
    """
    if not text:
        return text
    is_sqlplus = ('SQL*Plus' in text) or ('SQL>' in text)
    if not is_sqlplus:
        return text
    lines = text.splitlines()
    result: list[str] = []
    in_query = False
    prompt_re = re.compile(r'^(?:SQL>\s*|\s*\d+\s+)+')
    trailing_prompt_re = re.compile(r'\s*SQL>\s*$')
    disconnect_strip_re = re.compile(
        r'\s*SQL>\s*Disconnected from.*$|\s*Disconnected from.*$'
    )
    for line in lines:
        if 'Disconnected from' in line:
            stripped = prompt_re.sub('', line)
            stripped = disconnect_strip_re.sub('', stripped)
            if stripped.strip():
                if in_query or 'SQL>' in line:
                    result.append(stripped.rstrip())
            break
        if not in_query:
            if 'SQL>' in line:
                in_query = True
                cleaned = prompt_re.sub('', line)
                cleaned = trailing_prompt_re.sub('', cleaned)
                if cleaned.strip():
                    result.append(cleaned.rstrip())
            continue
        cleaned = prompt_re.sub('', line)
        cleaned = trailing_prompt_re.sub('', cleaned)
        result.append(cleaned.rstrip())
    while result and not result[0].strip():
        result.pop(0)
    while result and not result[-1].strip():
        result.pop()
    return '\n'.join(result)


def _parse_csv_lines(text: str) -> list[list[str]]:
    """テキストから CSV (または空白2個以上で分割した固定幅) を行列にパース。"""
    import csv as _csv
    from io import StringIO
    if not text or not text.strip():
        return []
    lines = text.splitlines()
    first_data_idx = 0
    for i, line in enumerate(lines):
        s = line.strip()
        if not s:
            continue
        if s.startswith('--'):
            continue
        if s.startswith('(') and s.endswith(')'):
            continue
        first_data_idx = i
        break
    clean_text = '\n'.join(lines[first_data_idx:])
    if not clean_text.strip():
        return []
    if clean_text.count(',') >= 1:
        try:
            reader = _csv.reader(StringIO(clean_text))
            rows = [row for row in reader if row]
            max_cols = max((len(r) for r in rows), default=0)
            if max_cols >= 2:
                return rows
        except Exception:
            pass
    rows: list[list[str]] = []
    for line in clean_text.splitlines():
        if not line.strip():
            continue
        cells = re.split(r' {2,}|\t+', line.strip())
        rows.append(cells)
    return rows


def _load_db_profiles() -> dict:
    try:
        with open(_DB_PROFILES_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _save_db_profiles(profiles: dict):
    try:
        with open(_DB_PROFILES_PATH, 'w', encoding='utf-8') as f:
            json.dump(profiles, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _load_history() -> list[str]:
    try:
        with open(_SORA_DB_HISTORY_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return [s for s in data if isinstance(s, str)] if isinstance(data, list) else []
    except Exception:
        return []


def _save_history(items: list[str], cap: int = 30):
    try:
        with open(_SORA_DB_HISTORY_PATH, 'w', encoding='utf-8') as f:
            json.dump(items[:cap], f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# SSH 経由でリモートシェルを実行するワーカー
# ---------------------------------------------------------------------------
class _SshExecWorker(QThread):
    finished_ok = pyqtSignal(str, str, int)   # stdout, stderr, exit_code
    finished_err = pyqtSignal(str)            # error message

    def __init__(self, profile: dict, command: str, parent=None):
        super().__init__(parent)
        self._profile = profile
        self._command = command

    def run(self):
        try:
            import paramiko
        except ImportError:
            self.finished_err.emit(
                "paramiko 未インストール。\n  pip install paramiko"
            )
            return
        host = self._profile.get('host', '')
        port = int(self._profile.get('port', 22) or 22)
        user = self._profile.get('user', '')
        password = self._profile.get('password', '')
        key_path = self._profile.get('key_path', '')
        client = None
        script_path = None
        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            if key_path and os.path.isfile(key_path):
                client.connect(host, port=port, username=user,
                               key_filename=key_path, timeout=15,
                               look_for_keys=False, allow_agent=False)
            else:
                client.connect(host, port=port, username=user,
                               password=password, timeout=15,
                               look_for_keys=False, allow_agent=False)
            # SFTP でリモート /tmp にスクリプトを書き込み、 bash --login で実行。
            # exec_command の -c 経由でヒアドキュメントを送ると改行が
            # 失われて <<'EOF' ... EOF の終端が認識されないため。
            import time as _time
            script_path = (
                f"/tmp/sora_db_exec_{int(_time.time() * 1000)}_{os.getpid()}.sh"
            )
            script_content = (
                "#!/bin/bash --login\n"
                "set -o pipefail\n"
                + self._command
                + ("\n" if not self._command.endswith("\n") else "")
            )
            sftp = client.open_sftp()
            try:
                with sftp.open(script_path, "w") as f:
                    f.write(script_content)
                sftp.chmod(script_path, 0o700)
            finally:
                try:
                    sftp.close()
                except Exception:
                    pass
            stdin_ch, stdout, stderr = client.exec_command(
                f"bash --login {script_path}",
                timeout=180, get_pty=False,
            )
            out = stdout.read().decode('utf-8', errors='replace')
            err = stderr.read().decode('utf-8', errors='replace')
            exit_code = stdout.channel.recv_exit_status()
            self.finished_ok.emit(out, err, exit_code)
        except Exception as e:
            self.finished_err.emit(f"{type(e).__name__}: {e}")
        finally:
            # スクリプトを削除 (失敗しても無視)
            if script_path and client is not None:
                try:
                    sftp = client.open_sftp()
                    try:
                        sftp.remove(script_path)
                    finally:
                        sftp.close()
                except Exception:
                    pass
            try:
                if client is not None:
                    client.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# 結果表示パネル — Sora 本体の DBExecuteDialog と機能等価:
#   - 4 表示モード: 全件(横・グリッド) / 全件(縦・転置) / 1件詳細(縦) / テキスト
#   - レコードナビ (1件詳細モードで <<, <, [N], >, >>)
#   - SQL*Plus 出力の自動クレンジング (_clean_sqlplus_output)
#   - CSV パース (_parse_csv_lines) と 0 件メッセージ
# ---------------------------------------------------------------------------
class _ResultPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._last_output_text: str = ''
        self._parsed_rows: list[list[str]] = []
        self._current_record: int = 0

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        # 上部ヘッダ: 表示モード + レコードナビ + コピー/保存 + 件数
        header = QHBoxLayout()
        result_lbl = QLabel("実行結果:")
        result_lbl.setStyleSheet("font-weight:600;")
        header.addWidget(result_lbl)
        header.addStretch()

        # レコードナビゲーション (1件詳細モードのみ可視)
        self.rec_first_btn = QPushButton("<<")
        self.rec_prev_btn  = QPushButton("<")
        self.rec_index_spin = QSpinBox()
        self.rec_index_spin.setMinimum(1)
        self.rec_index_spin.setMaximum(1)
        self.rec_index_spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.rec_index_spin.setFixedWidth(70)
        self.rec_index_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.rec_total_lbl = QLabel("/ 1")
        self.rec_next_btn  = QPushButton(">")
        self.rec_last_btn  = QPushButton(">>")
        for b in (self.rec_first_btn, self.rec_prev_btn,
                  self.rec_next_btn, self.rec_last_btn):
            b.setMinimumWidth(34)
            b.setAutoDefault(False)
        self.rec_first_btn.clicked.connect(lambda: self._goto_record(0))
        self.rec_prev_btn.clicked.connect(
            lambda: self._goto_record(self._current_record - 1))
        self.rec_next_btn.clicked.connect(
            lambda: self._goto_record(self._current_record + 1))
        self.rec_last_btn.clicked.connect(
            lambda: self._goto_record(self._record_count() - 1))
        self.rec_index_spin.editingFinished.connect(
            lambda: self._goto_record(self.rec_index_spin.value() - 1))
        for w in (self.rec_first_btn, self.rec_prev_btn, self.rec_index_spin,
                  self.rec_total_lbl, self.rec_next_btn, self.rec_last_btn):
            w.setVisible(False)
            header.addWidget(w)

        header.addSpacing(8)
        header.addWidget(QLabel("表示形式:"))
        self.view_mode_combo = QComboBox()
        self.view_mode_combo.addItem("📊 全件 (横・グリッド)", "grid")
        self.view_mode_combo.addItem("📋 全件 (縦・転置)", "vertical_all")
        self.view_mode_combo.addItem("🔍 1件詳細 (縦)", "vertical")
        self.view_mode_combo.addItem("テキスト", "text")
        self.view_mode_combo.setToolTip(
            "全件(横): 通常のグリッド表示。1行=1レコード、横スクロール\n"
            "全件(縦・転置): 列名を左ヘッダー、各レコードを横方向の列\n"
            "1件詳細(縦): 選択した1レコードのみを項目|値で縦表示 (◁▷で巡回)\n"
            "テキスト: 生の出力をそのまま表示"
        )
        self.view_mode_combo.currentIndexChanged.connect(self._on_view_mode_changed)
        header.addWidget(self.view_mode_combo)

        header.addSpacing(8)
        self.copy_btn = QPushButton("📋 結果コピー")
        self.copy_btn.setAutoDefault(False)
        self.copy_btn.clicked.connect(self._on_copy)
        header.addWidget(self.copy_btn)
        self.export_btn = QPushButton("💾 CSV 保存")
        self.export_btn.setAutoDefault(False)
        self.export_btn.clicked.connect(self._on_export)
        header.addWidget(self.export_btn)

        self.summary_label = QLabel("")
        self.summary_label.setStyleSheet("color:#888; font-size:11px;")
        header.addWidget(self.summary_label)
        layout.addLayout(header)

        # スタック: 0=テキスト / 1=テーブル (Sora と同順)
        self.result_stack = QStackedWidget()
        self.result_view = QPlainTextEdit()
        self.result_view.setFont(QFont("Consolas", 10))
        self.result_view.setReadOnly(True)
        self.result_stack.addWidget(self.result_view)

        self.result_table = QTableWidget()
        self.result_table.setAlternatingRowColors(True)
        self.result_table.setSortingEnabled(False)
        self.result_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.result_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.result_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive)
        self.result_table.horizontalHeader().setStretchLastSection(True)
        self.result_table.verticalHeader().setVisible(True)
        self.result_stack.addWidget(self.result_table)
        # 起動時はグリッド表示
        self.result_stack.setCurrentIndex(1)

        layout.addWidget(self.result_stack, 1)
        self.setLayout(layout)

    # ---- 入口 ----
    def show_text(self, text: str):
        """SSH 実行結果のテキストを受けて表示更新。
        SQL*Plus 出力なら自動でバナー/プロンプトを除去する。"""
        cleaned = _clean_sqlplus_output(text)
        self._last_output_text = cleaned
        self.result_view.setPlainText(cleaned)
        mode = self.view_mode_combo.currentData()
        if mode == "grid":
            self._render_grid(cleaned)
        elif mode == "vertical_all":
            self._render_vertical_all(cleaned)
        elif mode == "vertical":
            self._render_vertical(cleaned)
        # サマリ更新
        rows = _parse_csv_lines(cleaned) if cleaned.strip() else []
        ncount = max(0, len(rows) - 1) if rows else 0
        self.summary_label.setText(f"{ncount} 件")

    def show_error(self, msg: str):
        self._last_output_text = msg
        self.result_view.setPlainText(msg)
        # エラーはテキストモードへ強制切替
        idx = self.view_mode_combo.findData("text")
        if idx >= 0:
            self.view_mode_combo.blockSignals(True)
            self.view_mode_combo.setCurrentIndex(idx)
            self.view_mode_combo.blockSignals(False)
            self._on_view_mode_changed(idx)
        self.summary_label.setText("エラー")

    # ---- モード切替 ----
    def _on_view_mode_changed(self, _idx: int):
        mode = self.view_mode_combo.currentData()
        nav_visible = (mode == "vertical")
        for w in (self.rec_first_btn, self.rec_prev_btn, self.rec_index_spin,
                  self.rec_total_lbl, self.rec_next_btn, self.rec_last_btn):
            w.setVisible(nav_visible)
        text = self._last_output_text
        if mode == "grid":
            self._render_grid(text)
            self.result_stack.setCurrentIndex(1)
        elif mode == "vertical_all":
            self._render_vertical_all(text)
            self.result_stack.setCurrentIndex(1)
        elif mode == "vertical":
            self._render_vertical(text)
            self.result_stack.setCurrentIndex(1)
        else:
            self.result_stack.setCurrentIndex(0)

    # ---- レンダ: 横グリッド ----
    def _render_grid(self, text: str):
        self.result_table.setSortingEnabled(False)
        self.result_table.clear()

        def show_msg(msg: str):
            self.result_table.setColumnCount(1)
            self.result_table.setHorizontalHeaderLabels(["メッセージ"])
            self.result_table.setRowCount(1)
            item = QTableWidgetItem(msg)
            item.setForeground(QColor("#e0a96b"))
            f = item.font(); f.setBold(True); item.setFont(f)
            self.result_table.setItem(0, 0, item)
            self.result_table.resizeColumnsToContents()

        if not text or not text.strip():
            show_msg("⚠ 0 件 / 該当データなし (SQLは正常完了)")
            return
        rows = _parse_csv_lines(text)
        self._parsed_rows = rows
        if not rows:
            show_msg("⚠ 0 件 / 該当データなし (SQLは正常完了)")
            return
        if len(rows) == 1:
            ncols = len(rows[0])
            self.result_table.setColumnCount(ncols)
            self.result_table.setHorizontalHeaderLabels(
                [h.strip() or f"col{i+1}" for i, h in enumerate(rows[0])]
            )
            self.result_table.setRowCount(1)
            ph = QTableWidgetItem("⚠ 0 件 / 該当データなし")
            ph.setForeground(QColor("#e0a96b"))
            f = ph.font(); f.setBold(True); ph.setFont(f)
            self.result_table.setItem(0, 0, ph)
            if ncols > 1:
                self.result_table.setSpan(0, 0, 1, ncols)
            self.result_table.resizeColumnsToContents()
            return
        ncols = max(len(r) for r in rows)
        header = rows[0] + [''] * (ncols - len(rows[0]))
        body = rows[1:]
        self.result_table.setColumnCount(ncols)
        self.result_table.setHorizontalHeaderLabels(
            [h.strip() or f"col{i+1}" for i, h in enumerate(header)]
        )
        self.result_table.setRowCount(len(body))
        for r, row in enumerate(body):
            for c in range(ncols):
                val = row[c] if c < len(row) else ''
                self.result_table.setItem(r, c, QTableWidgetItem(val))
        self.result_table.resizeColumnsToContents()
        for c in range(ncols):
            if self.result_table.columnWidth(c) > 400:
                self.result_table.setColumnWidth(c, 400)
        self.result_table.setSortingEnabled(True)

    # ---- レンダ: 全件 縦転置 ----
    def _render_vertical_all(self, text: str):
        self.result_table.setSortingEnabled(False)
        self.result_table.clear()
        self.result_table.setRowCount(0)
        self.result_table.setColumnCount(0)
        rows = _parse_csv_lines(text) if text and text.strip() else []
        self._parsed_rows = rows
        if not rows:
            self.result_table.setColumnCount(1)
            self.result_table.setHorizontalHeaderLabels(["メッセージ"])
            self.result_table.setRowCount(1)
            it = QTableWidgetItem("⚠ 0 件 / 該当データなし (SQLは正常完了)")
            it.setForeground(QColor("#e0a96b"))
            f = it.font(); f.setBold(True); it.setFont(f)
            self.result_table.setItem(0, 0, it)
            self.result_table.resizeColumnsToContents()
            return
        header = rows[0]
        body = rows[1:]
        n_fields = len(header)
        n_records = len(body)
        if n_records == 0:
            self.result_table.setRowCount(n_fields)
            self.result_table.setColumnCount(1)
            self.result_table.setVerticalHeaderLabels(
                [(h or '').strip() or f"col{i+1}" for i, h in enumerate(header)]
            )
            self.result_table.setHorizontalHeaderLabels(["値"])
            for i in range(n_fields):
                ph = QTableWidgetItem("⚠ 0 件")
                ph.setForeground(QColor("#e0a96b"))
                self.result_table.setItem(i, 0, ph)
            self.result_table.resizeColumnsToContents()
            return
        self.result_table.setRowCount(n_fields)
        self.result_table.setColumnCount(n_records)
        self.result_table.setVerticalHeaderLabels(
            [(h or '').strip() or f"col{i+1}" for i, h in enumerate(header)]
        )
        self.result_table.setHorizontalHeaderLabels(
            [f"#{i+1}" for i in range(n_records)]
        )
        for col_idx, record in enumerate(body):
            for row_idx in range(n_fields):
                val = record[row_idx] if row_idx < len(record) else ''
                self.result_table.setItem(row_idx, col_idx, QTableWidgetItem(val))
        self.result_table.resizeColumnsToContents()
        for c in range(n_records):
            if self.result_table.columnWidth(c) > 400:
                self.result_table.setColumnWidth(c, 400)

    # ---- レンダ: 1件詳細 縦 ----
    def _render_vertical(self, text: str):
        rows = _parse_csv_lines(text) if text and text.strip() else []
        self._parsed_rows = rows
        total = self._record_count()
        if self._current_record >= total:
            self._current_record = max(0, total - 1)
        self._render_vertical_current()
        self._update_record_nav()

    def _record_count(self) -> int:
        if not self._parsed_rows or len(self._parsed_rows) < 2:
            return 0
        return len(self._parsed_rows) - 1

    def _update_record_nav(self):
        total = self._record_count()
        self.rec_index_spin.blockSignals(True)
        self.rec_index_spin.setMinimum(1)
        self.rec_index_spin.setMaximum(max(1, total))
        self.rec_index_spin.setValue(self._current_record + 1 if total > 0 else 1)
        self.rec_index_spin.blockSignals(False)
        self.rec_total_lbl.setText(f"/ {total}")
        self.rec_first_btn.setEnabled(self._current_record > 0)
        self.rec_prev_btn.setEnabled(self._current_record > 0)
        self.rec_next_btn.setEnabled(self._current_record < total - 1)
        self.rec_last_btn.setEnabled(self._current_record < total - 1)

    def _goto_record(self, idx: int):
        total = self._record_count()
        if total <= 0:
            return
        idx = max(0, min(idx, total - 1))
        self._current_record = idx
        self._render_vertical_current()
        self._update_record_nav()

    def _render_vertical_current(self):
        self.result_table.setSortingEnabled(False)
        self.result_table.clear()
        self.result_table.setRowCount(0)
        self.result_table.setColumnCount(0)
        rows = self._parsed_rows
        if not rows or len(rows) < 1:
            self.result_table.setColumnCount(1)
            self.result_table.setHorizontalHeaderLabels(["#1"])
            self.result_table.setRowCount(1)
            it = QTableWidgetItem("⚠ 0 件 / 該当データなし (SQLは正常完了)")
            it.setForeground(QColor("#e0a96b"))
            f = it.font(); f.setBold(True); it.setFont(f)
            self.result_table.setItem(0, 0, it)
            self.result_table.resizeColumnsToContents()
            return
        header = rows[0]
        body = rows[1:]
        n_fields = len(header)
        if not body:
            self.result_table.setRowCount(n_fields)
            self.result_table.setColumnCount(1)
            self.result_table.setVerticalHeaderLabels(
                [(h or '').strip() or f"col{i+1}" for i, h in enumerate(header)]
            )
            self.result_table.setHorizontalHeaderLabels(["#1"])
            for i in range(n_fields):
                ph = QTableWidgetItem("⚠ 0 件")
                ph.setForeground(QColor("#e0a96b"))
                self.result_table.setItem(i, 0, ph)
            self.result_table.resizeColumnsToContents()
            return
        idx = max(0, min(self._current_record, len(body) - 1))
        record = body[idx]
        self.result_table.setRowCount(n_fields)
        self.result_table.setColumnCount(1)
        self.result_table.setVerticalHeaderLabels(
            [(h or '').strip() or f"col{i+1}" for i, h in enumerate(header)]
        )
        self.result_table.setHorizontalHeaderLabels([f"#{idx + 1}"])
        for i in range(n_fields):
            val = record[i] if i < len(record) else ''
            self.result_table.setItem(i, 0, QTableWidgetItem(val))
        self.result_table.resizeColumnsToContents()
        if self.result_table.columnWidth(0) > 600:
            self.result_table.setColumnWidth(0, 600)

    # ---- コピー / CSV 保存 ----
    def _on_copy(self):
        QApplication.clipboard().setText(self._last_output_text or '')

    def _on_export(self):
        if not self._parsed_rows:
            QMessageBox.information(self, "保存", "保存できる結果がありません。")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "CSV 保存", "result.csv",
            "CSV (*.csv);;TSV (*.tsv);;すべて (*)"
        )
        if not path:
            return
        delim = '\t' if path.lower().endswith('.tsv') else ','
        import csv as _csv
        try:
            with open(path, 'w', newline='', encoding='utf-8-sig') as f:
                w = _csv.writer(f, delimiter=delim)
                for row in self._parsed_rows:
                    w.writerow(row)
        except Exception as e:
            QMessageBox.critical(self, "保存エラー", str(e))


# ---------------------------------------------------------------------------
# メインウィンドウ
# ---------------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self, initial_query: str = '', initial_profile: str = ''):
        super().__init__()
        self.setWindowTitle(f"Sora DB  v{__version__}")
        self.resize(1100, 720)
        self._profiles = _load_db_profiles()
        self._worker: _SshExecWorker | None = None

        self._build_ui()
        self._build_menu()

        # 初期プロファイル選択 → _on_profile_changed が cmd_edit を更新
        if initial_profile:
            i = self.profile_combo.findText(initial_profile)
            if i >= 0:
                self.profile_combo.setCurrentIndex(i)
        else:
            # 先頭プロファイルでも cmd_edit を初期化させる
            if self.profile_combo.count() > 0:
                self._on_profile_changed(self.profile_combo.currentText())
        if initial_query:
            self.query_edit.setPlainText(initial_query)

    def _build_ui(self):
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(4)

        # トップ: プロファイル + プリセット + 実行ボタン
        top = QHBoxLayout()
        top.addWidget(QLabel("接続プロファイル:"))
        self.profile_combo = QComboBox()
        self.profile_combo.setMinimumWidth(260)
        self._refresh_profile_combo()
        self.profile_combo.currentTextChanged.connect(self._on_profile_changed)
        top.addWidget(self.profile_combo)

        top.addSpacing(12)
        top.addWidget(QLabel("DBプリセット:"))
        self.preset_combo = QComboBox()
        self.preset_combo.addItem("（選択して挿入）")
        for name in _DB_CMD_PRESETS:
            self.preset_combo.addItem(name)
        self.preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        self.preset_combo.setFixedWidth(180)
        top.addWidget(self.preset_combo)

        # コマンド設定欄の折りたたみトグル
        self.cmd_toggle_btn = QPushButton("▼ DB実行コマンド設定")
        self.cmd_toggle_btn.setCheckable(True)
        self.cmd_toggle_btn.setChecked(True)
        self.cmd_toggle_btn.setToolTip(
            "DB実行コマンドテンプレート (USER/PASS/SID を実値に書き換えて使用)"
        )
        self.cmd_toggle_btn.clicked.connect(self._toggle_cmd_section)
        top.addWidget(self.cmd_toggle_btn)

        top.addStretch()
        self.run_btn = QPushButton("▶ 実行 (Ctrl+Enter)")
        self.run_btn.setShortcut(QKeySequence("Ctrl+Return"))
        self.run_btn.clicked.connect(self._on_run)
        self.run_btn.setStyleSheet(
            "QPushButton { background:#2E7D32; color:white; padding:5px 14px;"
            " border:none; border-radius:3px; font-weight:700; }"
            "QPushButton:hover { background:#388E3C; }"
            "QPushButton:disabled { background:#999; }"
        )
        top.addWidget(self.run_btn)
        root.addLayout(top, 0)

        # DB実行コマンドテンプレート (折りたたみ可能、 プロファイル毎に保存)
        self.cmd_section = QWidget()
        cs_l = QVBoxLayout(self.cmd_section)
        cs_l.setContentsMargins(0, 0, 0, 0)
        cs_l.setSpacing(2)
        cs_l.addWidget(QLabel(
            "DB実行コマンド (USER/PASS/SID は実値に置換、 {SQL} が SQL に展開):"
        ))
        self.cmd_edit = QPlainTextEdit()
        self.cmd_edit.setFont(QFont("Consolas", 10))
        self.cmd_edit.setMaximumHeight(120)
        self.cmd_edit.setPlaceholderText(
            "例:  sqlplus -S scott/tiger@xe <<'EOF'\n"
            "set markup csv on quote on\n"
            "set feedback off pagesize 0\n"
            "{SQL};\nexit\nEOF"
        )
        cs_l.addWidget(self.cmd_edit)
        cs_btn_row = QHBoxLayout()
        self.save_cmd_btn = QPushButton("💾 このプロファイルに保存")
        self.save_cmd_btn.setAutoDefault(False)
        self.save_cmd_btn.clicked.connect(self._on_save_cmd)
        cs_btn_row.addWidget(self.save_cmd_btn)
        self.autosave_label = QLabel(
            " ※ 編集中は 500ms 後に自動でこのプロファイルへ保存されます"
        )
        self.autosave_label.setStyleSheet("color:#888; font-size:11px;")
        cs_btn_row.addWidget(self.autosave_label)
        cs_btn_row.addStretch()
        cs_l.addLayout(cs_btn_row)
        root.addWidget(self.cmd_section, 0)

        # 自動保存タイマー (textChanged 後 500ms で _on_save_cmd を発火)
        from PyQt6.QtCore import QTimer
        self._cmd_save_timer = QTimer(self)
        self._cmd_save_timer.setSingleShot(True)
        self._cmd_save_timer.setInterval(500)
        self._cmd_save_timer.timeout.connect(self._autosave_cmd)
        self.cmd_edit.textChanged.connect(self._cmd_save_timer.start)
        # プロファイル切替直後の textChanged (= setPlainText 由来) は
        # 自動保存しない (= "ロード=書き込み" の自己ループ防止)
        self._loading_cmd = False

        # 中央: 上=クエリエディタ / 下=結果
        splitter = QSplitter(Qt.Orientation.Vertical)
        # 上: クエリエディタ
        upper = QWidget()
        upper_l = QVBoxLayout(upper)
        upper_l.setContentsMargins(0, 0, 0, 0)
        upper_l.setSpacing(2)
        upper_l.addWidget(QLabel("SQL:"))
        self.query_edit = QPlainTextEdit()
        self.query_edit.setFont(QFont("Consolas", 11))
        self.query_edit.setPlaceholderText("SELECT * FROM ...")
        upper_l.addWidget(self.query_edit, 1)
        splitter.addWidget(upper)

        # 下: 結果
        self.result_panel = _ResultPanel()
        splitter.addWidget(self.result_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        root.addWidget(splitter, 1)

        self.setCentralWidget(central)

        # ステータスバー
        self.status_label = QLabel("待機中")
        sb = QStatusBar()
        sb.addPermanentWidget(self.status_label)
        self.setStatusBar(sb)

    def _build_menu(self):
        mb = self.menuBar()
        fm = mb.addMenu("ファイル(&F)")
        a_open = QAction("SQL を開く(&O)...", self)
        a_open.setShortcut(QKeySequence.StandardKey.Open)
        a_open.triggered.connect(self._on_open_sql)
        fm.addAction(a_open)
        a_save = QAction("SQL を保存(&S)...", self)
        a_save.setShortcut(QKeySequence.StandardKey.Save)
        a_save.triggered.connect(self._on_save_sql)
        fm.addAction(a_save)
        fm.addSeparator()
        a_quit = QAction("終了(&Q)", self)
        a_quit.setShortcut(QKeySequence("Ctrl+Q"))
        a_quit.triggered.connect(self.close)
        fm.addAction(a_quit)

        em = mb.addMenu("実行(&R)")
        a_run = QAction("実行(&R)", self)
        a_run.setShortcut(QKeySequence("Ctrl+Return"))
        a_run.triggered.connect(self._on_run)
        em.addAction(a_run)
        a_clear = QAction("結果クリア(&C)", self)
        a_clear.triggered.connect(self._clear_result)
        em.addAction(a_clear)

    def _refresh_profile_combo(self):
        self.profile_combo.clear()
        if not self._profiles:
            self.profile_combo.addItem("（プロファイル未登録）")
            return
        for name in sorted(self._profiles.keys()):
            self.profile_combo.addItem(name)

    def _on_preset_changed(self, idx: int):
        if idx <= 0:
            return
        name = self.preset_combo.itemText(idx)
        tmpl = _DB_CMD_PRESETS.get(name, '')
        if tmpl:
            self.cmd_edit.setPlainText(tmpl)
            self.status_label.setText(
                f"プリセット適用: {name} — USER/PASS/SID を実値に書き換えてください"
            )
            # 折りたたまれていたら展開
            if not self.cmd_toggle_btn.isChecked():
                self.cmd_toggle_btn.setChecked(True)
                self._toggle_cmd_section()
        # 次回も同じプリセットを選べるよう先頭に戻す
        self.preset_combo.blockSignals(True)
        self.preset_combo.setCurrentIndex(0)
        self.preset_combo.blockSignals(False)

    def _on_profile_changed(self, name: str):
        """プロファイル変更 → 保存済み db_exec_cmd を cmd_edit に展開。
        未設定なら空欄のまま (= プリセット選択を促す)。"""
        prof = self._profiles.get(name, {})
        cmd = prof.get('db_exec_cmd', '') or ''
        # ロード中は自動保存を抑止 (= 設定を空でクリアしてしまうのを防ぐ)
        self._loading_cmd = True
        self._cmd_save_timer.stop()
        self.cmd_edit.setPlainText(cmd)
        self._loading_cmd = False
        host = prof.get('host', '')
        user = prof.get('user', '')
        if host:
            self.status_label.setText(f"接続先: {user}@{host}")
        else:
            self.status_label.setText("プロファイル未選択")

    def _autosave_cmd(self):
        """textChanged → 500ms デバウンス → 現プロファイルへ保存。"""
        if self._loading_cmd:
            return
        name = self.profile_combo.currentText()
        if not name or name not in self._profiles:
            return
        new_cmd = self.cmd_edit.toPlainText()
        if self._profiles[name].get('db_exec_cmd', '') == new_cmd:
            return  # 変化なし
        self._profiles[name]['db_exec_cmd'] = new_cmd
        _save_db_profiles(self._profiles)
        self.status_label.setText(f"自動保存: {name}")

    def _toggle_cmd_section(self):
        visible = self.cmd_toggle_btn.isChecked()
        self.cmd_section.setVisible(visible)
        self.cmd_toggle_btn.setText(
            "▼ DB実行コマンド設定" if visible else "▶ DB実行コマンド設定"
        )

    def _on_save_cmd(self):
        name = self.profile_combo.currentText()
        if not name or name not in self._profiles:
            QMessageBox.warning(self, "プロファイル未選択",
                                "保存先のプロファイルが選択されていません。")
            return
        self._profiles[name]['db_exec_cmd'] = self.cmd_edit.toPlainText()
        _save_db_profiles(self._profiles)
        self.status_label.setText(f"DB実行コマンドを保存: {name}")

    def _on_open_sql(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "SQL ファイルを開く", "", "SQL (*.sql);;すべて (*)"
        )
        if not path:
            return
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                self.query_edit.setPlainText(f.read())
        except Exception as e:
            QMessageBox.critical(self, "読み込みエラー", str(e))

    def _on_save_sql(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "SQL を保存", "query.sql", "SQL (*.sql);;すべて (*)"
        )
        if not path:
            return
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(self.query_edit.toPlainText())
        except Exception as e:
            QMessageBox.critical(self, "保存エラー", str(e))

    def _clear_result(self):
        self.result_panel.show_text('')

    def _on_run(self):
        if self._worker is not None and self._worker.isRunning():
            return
        sql = self.query_edit.toPlainText().strip().rstrip(';')
        if not sql:
            QMessageBox.information(self, "SQL なし", "SQL を入力してください。")
            return
        prof_name = self.profile_combo.currentText()
        prof = self._profiles.get(prof_name)
        if not prof:
            QMessageBox.warning(self, "プロファイル未選択",
                                "接続プロファイルが見つかりません。\n"
                                "Multi-Server Log Viewer で登録してください。")
            return
        cmd_template = self.cmd_edit.toPlainText().strip()
        if not cmd_template:
            QMessageBox.warning(self, "DB実行コマンド未設定",
                                "DB実行コマンドが空です。\n"
                                "DBプリセット (Oracle (sqlplus) 等) を選んで\n"
                                "USER/PASS/SID を実値に書き換えてください。")
            return
        if '{SQL}' not in cmd_template:
            QMessageBox.warning(self, "{SQL} プレースホルダなし",
                                "テンプレートに {SQL} プレースホルダが含まれていません。")
            return
        # SQL を実行コマンドに埋め込む。 sqlplus はヒアドキュメント内に
        # そのまま入れるのでエスケープ不要 (シェル -c 経由でも repr()
        # しているため安全)
        cmd = cmd_template.replace('{SQL}', sql)
        self.run_btn.setEnabled(False)
        self.status_label.setText(f"実行中: {prof_name} ...")
        self._worker = _SshExecWorker(prof, cmd, self)
        self._worker.finished_ok.connect(self._on_exec_ok)
        self._worker.finished_err.connect(self._on_exec_err)
        self._worker.start()
        # 履歴に積む
        try:
            hist = _load_history()
            hist = [h for h in hist if h.strip() != sql.strip()]
            hist.insert(0, sql)
            _save_history(hist)
        except Exception:
            pass

    def _on_exec_ok(self, out: str, err: str, exit_code: int):
        self.run_btn.setEnabled(True)
        if exit_code != 0 and not out.strip():
            self.result_panel.show_error(
                f"-- exit_code={exit_code} --\nstderr:\n{err or '(なし)'}"
            )
            self.status_label.setText(f"エラー終了 (exit={exit_code})")
            return
        combined = out
        if err.strip():
            combined = out + "\n-- stderr --\n" + err
        self.result_panel.show_text(combined)
        self.status_label.setText(f"完了 (exit={exit_code})")

    def _on_exec_err(self, msg: str):
        self.run_btn.setEnabled(True)
        self.result_panel.show_error(msg)
        self.status_label.setText("接続/実行エラー")


# ---------------------------------------------------------------------------
# エントリ
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Sora DB")
    parser.add_argument('--profile', default='', help='初期選択するプロファイル名')
    parser.add_argument('--query',   default='', help='初期投入する SQL')
    args, _qt_args = parser.parse_known_args()

    app = QApplication(sys.argv)
    app.setApplicationName("Sora DB")
    win = MainWindow(initial_query=args.query, initial_profile=args.profile)
    win.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
