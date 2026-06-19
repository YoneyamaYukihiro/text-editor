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
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QPlainTextEdit, QPushButton, QLabel, QComboBox, QStatusBar, QStackedWidget,
    QTableView, QHeaderView, QAbstractItemView, QMessageBox, QFileDialog,
)
from PyQt6.QtGui import (
    QFont, QAction, QKeySequence, QStandardItemModel, QStandardItem,
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


def _load_db_profiles() -> dict:
    try:
        with open(_DB_PROFILES_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


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
            stdin_ch, stdout, stderr = client.exec_command(
                f"bash --login -c {repr(self._command)}",
                timeout=180, get_pty=False,
            )
            out = stdout.read().decode('utf-8', errors='replace')
            err = stderr.read().decode('utf-8', errors='replace')
            exit_code = stdout.channel.recv_exit_status()
            self.finished_ok.emit(out, err, exit_code)
        except Exception as e:
            self.finished_err.emit(f"{type(e).__name__}: {e}")
        finally:
            try:
                if client is not None:
                    client.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# 結果表示パネル: テキスト / グリッドの 2 モード
# ---------------------------------------------------------------------------
class _ResultPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        # 切替バー
        bar = QHBoxLayout()
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["📊 グリッド", "📝 テキスト"])
        self.mode_combo.setFixedWidth(120)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        self.export_btn = QPushButton("💾 CSV 保存")
        self.export_btn.setAutoDefault(False)
        self.export_btn.clicked.connect(self._on_export)
        self.summary_label = QLabel("結果なし")
        bar.addWidget(QLabel("表示:"))
        bar.addWidget(self.mode_combo)
        bar.addWidget(self.export_btn)
        bar.addStretch()
        bar.addWidget(self.summary_label)
        layout.addLayout(bar)

        self.stack = QStackedWidget()
        # 0: グリッド
        self.table = QTableView()
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive)
        self.stack.addWidget(self.table)
        # 1: テキスト
        self.text_view = QPlainTextEdit()
        self.text_view.setFont(QFont("Consolas", 11))
        self.text_view.setReadOnly(True)
        self.stack.addWidget(self.text_view)
        layout.addWidget(self.stack, 1)
        self.setLayout(layout)

        self._last_rows: list[list[str]] = []
        self._last_headers: list[str] = []

    def _on_mode_changed(self, idx: int):
        self.stack.setCurrentIndex(idx)

    def show_text(self, text: str):
        self.text_view.setPlainText(text)
        # CSV パースを試みて成功すればグリッドにも反映
        rows, headers = self._parse_csv(text)
        self._populate_grid(headers, rows)
        self.summary_label.setText(
            f"{len(rows)} 行" if rows else "結果なし"
        )

    def show_error(self, msg: str):
        self.text_view.setPlainText(msg)
        self._populate_grid([], [])
        self.summary_label.setText("エラー")
        self.stack.setCurrentIndex(1)   # エラーはテキストモードへ強制切替

    def _parse_csv(self, text: str) -> tuple[list[list[str]], list[str]]:
        # SQL*Plus markup csv 出力等を想定して csv.reader で行解析。
        # 失敗 / 1 列だけ等は ([], []) を返す。
        if not text.strip():
            return [], []
        import csv as _csv
        import io as _io
        try:
            lines = text.splitlines()
            reader = _csv.reader(lines)
            rows = [r for r in reader if r and any(c.strip() for c in r)]
        except Exception:
            return [], []
        if len(rows) < 1:
            return [], []
        ncols = max((len(r) for r in rows), default=1)
        rows = [r + [''] * (ncols - len(r)) for r in rows]
        # 1 行目をヘッダにする (Oracle markup csv で先頭が列名)
        headers = rows[0] if rows else [f"列{i+1}" for i in range(ncols)]
        data = rows[1:] if len(rows) > 1 else []
        return data, headers

    def _populate_grid(self, headers: list[str], rows: list[list[str]]):
        self._last_headers = headers
        self._last_rows = rows
        if not headers and not rows:
            self.table.setModel(QStandardItemModel(0, 0, self))
            return
        ncols = len(headers) or (len(rows[0]) if rows else 1)
        model = QStandardItemModel(len(rows), ncols, self)
        model.setHorizontalHeaderLabels([str(h) for h in headers])
        for r, row in enumerate(rows):
            for c in range(ncols):
                val = row[c] if c < len(row) else ''
                it = QStandardItem(str(val))
                it.setEditable(False)
                model.setItem(r, c, it)
        self.table.setModel(model)
        self.table.resizeColumnsToContents()
        for c in range(ncols):
            if self.table.columnWidth(c) > 400:
                self.table.setColumnWidth(c, 400)

    def _on_export(self):
        if not self._last_headers and not self._last_rows:
            QMessageBox.information(self, "保存", "保存できる結果がありません。")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "CSV 保存", "result.csv", "CSV (*.csv);;TSV (*.tsv);;すべて (*)"
        )
        if not path:
            return
        delim = '\t' if path.lower().endswith('.tsv') else ','
        import csv as _csv
        try:
            with open(path, 'w', newline='', encoding='utf-8-sig') as f:
                w = _csv.writer(f, delimiter=delim)
                w.writerow(self._last_headers)
                for row in self._last_rows:
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
        self._cmd_template = next(iter(_DB_CMD_PRESETS.values()))
        self._worker: _SshExecWorker | None = None

        self._build_ui()
        self._build_menu()

        if initial_profile:
            i = self.profile_combo.findText(initial_profile)
            if i >= 0:
                self.profile_combo.setCurrentIndex(i)
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
        self._cmd_template = _DB_CMD_PRESETS.get(name, self._cmd_template)
        self.status_label.setText(f"DBプリセット: {name}")

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
        # コマンド生成 (テンプレ → {SQL} 置換)
        cmd = self._cmd_template.replace('{SQL}', sql.replace('"', '\\"'))
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
