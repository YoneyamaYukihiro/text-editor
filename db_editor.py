#!/usr/bin/env python3
"""DB Editor — SSH 経由で更新系 SQL を安全に実行する編集ツール (Phase 1)

Sora Editor / Multi-Server Log Viewer とは独立した第3のアプリ。

設計方針 (提案・確定版):
  - 接続層は ssh_log_viewer の SSHConnection を再利用 (再実装しない)
  - 接続プロファイルは ~/.ssh_log_viewer_profiles.json を両アプリと共有
  - シンタックスハイライト / テーマは text_editor のものを流用
  - 既存 DBExecuteDialog は「参照専用」。本ツールは更新系 (INSERT/UPDATE/
    DELETE/MERGE 等) を実行できるが、その分だけ安全装置を厚くする。

トランザクション方式 (案A: ステージング + 一括TX):
  - 編集 SQL は 1 回の exec_command にまとめて送信し、テンプレート側で
    BEGIN ... COMMIT / エラー時 ROLLBACK を保証する。
  - セッションをまたがないため「SQL を流して確認してから人が commit」は
    できないが、実行前に dry-run と影響行プレビューで内容を確定できる。

Phase 1 の範囲:
  - 独立起動 + SSH 接続流用 + SQL タブ
  - 安全装置: 参照系/更新系の判別、WHERE 句必須チェック、危険 DDL の追加確認、
    dry-run、影響行プレビュー (COUNT)、実行前の最終確認ダイアログ
  - 監査ログ (~/.db_editor_audit.log)
  - グリッド編集タブは Phase 2 (本ファイルではプレースホルダ)
"""
__version__ = "0.1.0"

import sys
import os
import re
import json
import time
import datetime

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QComboBox, QPushButton, QPlainTextEdit, QTextEdit, QCheckBox, QMessageBox,
    QTabWidget, QStatusBar, QSplitter,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QShortcut, QKeySequence

# ── 既存資産の流用 (失敗してもツール自体は最低限動くようフォールバック) ──────
try:
    from ssh_log_viewer import SSHConnection  # 接続層を再利用 (intent: 既存SSH接続)
except Exception:  # pragma: no cover - 単体起動時の保険
    SSHConnection = None

try:
    from text_editor import (
        SyntaxHighlighter, _theme, _DB_PROFILES_PATH,
        _load_db_profiles, _save_db_profiles,
    )
except Exception:  # pragma: no cover
    SyntaxHighlighter = None
    _DB_PROFILES_PATH = os.path.join(os.path.expanduser('~'),
                                     '.ssh_log_viewer_profiles.json')

    def _theme() -> dict:
        return {'bg': '#2b2b2b', 'editor_bg': '#1e1e1e', 'text': '#dcdcdc'}

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


# ---------------------------------------------------------------------------
# 定数
# ---------------------------------------------------------------------------

_AUDIT_LOG_PATH = os.path.join(os.path.expanduser('~'), '.db_editor_audit.log')

# 編集系コマンドテンプレート。{SQL} を実 SQL で置換する。
# 既存 _DB_CMD_PRESETS (参照専用) と違い、トランザクションで包み、
# 失敗時は ROLLBACK されるようにしている。
_DB_EDIT_PRESETS = {
    "Oracle (sqlplus)": (
        "sqlplus -S USER/PASS@SID <<'EOF'\n"
        "whenever sqlerror exit failure rollback\n"
        "set echo off feedback on define off\n"
        "{SQL}\n"
        "commit;\n"
        "exit\nEOF"
    ),
    "MySQL/MariaDB": (
        "mysql -u USER -pPASS -h localhost DBNAME <<'EOF'\n"
        "START TRANSACTION;\n"
        "{SQL}\n"
        "COMMIT;\n"
        "EOF"
    ),
    "PostgreSQL": (
        "PGPASSWORD=PASS psql -h localhost -U USER -d DBNAME -v ON_ERROR_STOP=1 <<'EOF'\n"
        "BEGIN;\n"
        "{SQL}\n"
        "COMMIT;\n"
        "EOF"
    ),
    "SQLite": (
        "sqlite3 /path/to/db.sqlite <<'EOF'\n"
        ".bail on\n"
        "BEGIN;\n"
        "{SQL}\n"
        "COMMIT;\n"
        "EOF"
    ),
    "SQL Server (sqlcmd)": (
        'sqlcmd -S localhost -U USER -P PASS -d DBNAME -b -Q '
        '"SET XACT_ABORT ON; BEGIN TRAN; {SQL}; COMMIT TRAN"'
    ),
}

# 参照系の先頭キーワード (これらは「編集」ではないので影響行確認をスキップ)
_READ_ONLY_KEYWORDS = frozenset({'SELECT', 'WITH', 'EXPLAIN', 'DESC', 'DESCRIBE', 'SHOW'})
# 行に影響を与える DML (WHERE 必須チェックの対象)
_ROW_DML_KEYWORDS = frozenset({'UPDATE', 'DELETE'})
# 特に危険な DDL / 全件操作 (追加確認を必須にする)
_DANGEROUS_KEYWORDS = frozenset({'DROP', 'TRUNCATE', 'ALTER', 'GRANT', 'REVOKE', 'RENAME'})
# 編集系として許可する先頭キーワード全体
_EDIT_KEYWORDS = frozenset({
    'INSERT', 'UPDATE', 'DELETE', 'MERGE', 'TRUNCATE',
    'DROP', 'CREATE', 'ALTER', 'RENAME', 'GRANT', 'REVOKE',
    'CALL', 'EXEC', 'EXECUTE', 'BEGIN', 'DECLARE', 'SET', 'REPLACE',
})


# ---------------------------------------------------------------------------
# SQL 解析ヘルパ (text_editor の手法を踏襲した軽量実装)
# ---------------------------------------------------------------------------

def _strip_leading_comments(sql: str) -> str:
    s = sql.lstrip()
    while True:
        if s.startswith('--'):
            nl = s.find('\n')
            s = (s[nl + 1:] if nl >= 0 else '').lstrip()
            continue
        if s.startswith('/*'):
            end = s.find('*/')
            s = (s[end + 2:] if end >= 0 else '').lstrip()
            continue
        break
    return s


def _first_keyword(sql: str) -> str:
    s = _strip_leading_comments(sql)
    m = re.match(r'(\w+)', s)
    return m.group(1).upper() if m else ''


def _strip_strings_and_comments(sql: str) -> str:
    """文字列リテラル・コメントを潰した検査用文字列を返す (偽陽性防止)。"""
    s = re.sub(r'--[^\n]*', ' ', sql)
    s = re.sub(r'/\*.*?\*/', ' ', s, flags=re.DOTALL)
    s = re.sub(r"'(?:[^']|'')*'", "''", s)
    s = re.sub(r'"(?:[^"]|"")*"', '""', s)
    return s


def _split_statements(sql: str) -> list[str]:
    """トップレベルの ; で文を分割する (文字列内の ; は無視)。"""
    out, buf, i, n = [], [], 0, len(sql)
    in_str = False
    while i < n:
        ch = sql[i]
        if ch == "'":
            buf.append(ch)
            in_str = not in_str
        elif ch == ';' and not in_str:
            stmt = ''.join(buf).strip()
            if stmt:
                out.append(stmt)
            buf = []
        else:
            buf.append(ch)
        i += 1
    tail = ''.join(buf).strip()
    if tail:
        out.append(tail)
    return out


def _has_where_clause(stmt: str) -> bool:
    return re.search(r'\bWHERE\b', _strip_strings_and_comments(stmt), re.IGNORECASE) is not None


def _build_count_query(stmt: str) -> str:
    """UPDATE/DELETE 文から影響行数を数える SELECT COUNT(*) を best-effort で生成。
    生成できない場合は '' を返す。
    """
    kw = _first_keyword(stmt)
    body = stmt.rstrip().rstrip(';')
    if kw == 'DELETE':
        m = re.match(r'(?is)\s*DELETE\s+FROM\s+(.+?)\s+WHERE\b(.*)$', body)
        if m:
            return f"SELECT COUNT(*) FROM {m.group(1).strip()} WHERE {m.group(2).strip()}"
    elif kw == 'UPDATE':
        # UPDATE <table> SET ... WHERE <cond>  (最初の SET と 最初の WHERE で切る)
        m = re.match(r'(?is)\s*UPDATE\s+(.+?)\s+SET\s+.*?\bWHERE\b(.*)$', body)
        if m:
            return f"SELECT COUNT(*) FROM {m.group(1).strip()} WHERE {m.group(2).strip()}"
    return ''


def _classify(sql: str) -> tuple[str, list[str]]:
    """SQL 全体を分類する。
    返り値: (種別, 注意メッセージのリスト)
      種別: 'read' / 'edit' / 'empty'
    """
    statements = _split_statements(sql)
    if not statements:
        return 'empty', []
    notes: list[str] = []
    kind = 'read'
    for st in statements:
        kw = _first_keyword(st)
        if kw in _EDIT_KEYWORDS or kw in _DANGEROUS_KEYWORDS:
            kind = 'edit'
            if kw in _ROW_DML_KEYWORDS and not _has_where_clause(st):
                notes.append(f"⚠ WHERE 句のない {kw} 文があります (全件操作の恐れ)")
            if kw in _DANGEROUS_KEYWORDS or kw == 'TRUNCATE':
                notes.append(f"⚠ 破壊的な操作 ({kw}) が含まれています")
        elif kw not in _READ_ONLY_KEYWORDS:
            # 未知キーワードは編集扱い (安全側)
            kind = 'edit'
    return kind, notes


def _append_audit(profile: str, sql: str, status: str, detail: str = ''):
    """実行した編集系 SQL を監査ログに追記する。"""
    try:
        ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with open(_AUDIT_LOG_PATH, 'a', encoding='utf-8') as f:
            f.write(f"\n===== {ts} | profile={profile} | {status} =====\n")
            if detail:
                f.write(f"-- {detail}\n")
            f.write(sql.rstrip() + "\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# SSH 実行ワーカー (UI を固めないよう別スレッドで実行)
# ---------------------------------------------------------------------------

class _ExecWorker(QThread):
    finished_ok = pyqtSignal(str, str, int)   # stdout, stderr, exit_code
    failed = pyqtSignal(str)                   # error message

    def __init__(self, profile: dict, cmd_body: str, parent=None):
        super().__init__(parent)
        self._profile = profile
        self._cmd_body = cmd_body

    def run(self):
        try:
            import paramiko
        except ImportError:
            self.failed.emit("paramiko が必要です: pip install paramiko")
            return

        prof = self._profile
        host = prof.get('host', '')
        port = int(prof.get('port', 22) or 22)
        user = prof.get('user', '')
        password = prof.get('password', '')
        key_path = prof.get('key_path', '')

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

            # SFTP で一時スクリプトを書いて bash -l で実行 (DBExecuteDialog と同方式)
            script_path = f"/tmp/db_editor_{int(time.time() * 1000)}_{os.getpid()}.sh"
            script_content = (
                "#!/bin/bash --login\n"
                "set -o pipefail\n"
                + self._cmd_body
                + ("\n" if not self._cmd_body.endswith("\n") else "")
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

            _, stdout, stderr = client.exec_command(
                f"bash --login {script_path}", timeout=180, get_pty=False
            )
            out = stdout.read().decode('utf-8', errors='replace')
            err = stderr.read().decode('utf-8', errors='replace')
            exit_code = stdout.channel.recv_exit_status()

            try:
                sftp = client.open_sftp()
                sftp.remove(script_path)
                sftp.close()
            except Exception:
                pass

            self.finished_ok.emit(out, err, exit_code)
        except Exception as e:
            self.failed.emit(str(e))
        finally:
            try:
                if client is not None:
                    client.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# SQL 実行タブ (Phase 1 の本体)
# ---------------------------------------------------------------------------

class SqlEditTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._profiles = _load_db_profiles()
        self._worker = None
        self._pending_sql = ''        # 実行確定済みの編集 SQL (監査用)
        self._mode = None             # 'count' or 'exec'
        self._build_ui()
        self._refresh_profiles()

    # ── UI 構築 ──────────────────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # プロファイル + プリセット行
        top = QHBoxLayout()
        top.addWidget(QLabel("接続プロファイル:"))
        self.profile_combo = QComboBox()
        self.profile_combo.setMinimumWidth(220)
        self.profile_combo.currentTextChanged.connect(self._on_profile_changed)
        top.addWidget(self.profile_combo)

        top.addSpacing(8)
        self.cmd_toggle = QPushButton("▶ DB実行コマンド設定")
        self.cmd_toggle.setCheckable(True)
        self.cmd_toggle.clicked.connect(self._toggle_cmd)
        top.addWidget(self.cmd_toggle)

        top.addSpacing(8)
        top.addWidget(QLabel("DBプリセット:"))
        self.preset_combo = QComboBox()
        self.preset_combo.addItem("（選択）")
        for name in _DB_EDIT_PRESETS:
            self.preset_combo.addItem(name)
        self.preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        top.addWidget(self.preset_combo)
        top.addStretch()

        # 編集許可フラグ (プロファイル別)
        self.allow_edit_chk = QCheckBox("このプロファイルで編集を許可")
        self.allow_edit_chk.setToolTip(
            "本番DBなど更新を絶対に避けたい接続では OFF のままにしてください。\n"
            "OFF の間は更新系 SQL の実行をブロックします。")
        self.allow_edit_chk.stateChanged.connect(self._on_allow_edit_changed)
        top.addWidget(self.allow_edit_chk)
        root.addLayout(top)

        # コマンドテンプレート (折りたたみ)
        self.cmd_input = QPlainTextEdit()
        self.cmd_input.setFont(QFont("Consolas", 10))
        self.cmd_input.setMaximumHeight(120)
        self.cmd_input.setPlaceholderText(
            "右上の DBプリセットから雛形を選び、USER/PASS/SID 等を実値に書き換えてください。\n"
            "{SQL} が編集SQLで置換されます。テンプレートは BEGIN..COMMIT で囲み、\n"
            "失敗時は ROLLBACK される構成です。")
        self.cmd_input.setVisible(False)
        root.addWidget(self.cmd_input)

        cmd_btn_row = QHBoxLayout()
        cmd_btn_row.addStretch()
        self.save_cmd_btn = QPushButton("コマンドをプロファイルに保存")
        self.save_cmd_btn.clicked.connect(self._save_cmd)
        self.save_cmd_btn.setVisible(False)
        cmd_btn_row.addWidget(self.save_cmd_btn)
        root.addLayout(cmd_btn_row)

        # SQL 入力 / 結果のスプリッタ
        splitter = QSplitter(Qt.Orientation.Vertical)

        sql_box = QWidget()
        sql_layout = QVBoxLayout(sql_box)
        sql_layout.setContentsMargins(0, 0, 0, 0)
        sql_layout.addWidget(QLabel("実行する SQL (INSERT/UPDATE/DELETE 等。複数文は ; 区切り):"))
        self.sql_input = QPlainTextEdit()
        self.sql_input.setFont(QFont("Consolas", 11))
        th = _theme()
        self.sql_input.setStyleSheet(
            f"QPlainTextEdit {{ border:2px solid #c84a4a;"
            f" background:{th.get('editor_bg', '#1e1e1e')};"
            f" color:{th.get('text', '#dcdcdc')}; }}")
        self.sql_input.setToolTip("更新系 SQL を入力します (赤枠 = 編集モード)")
        if SyntaxHighlighter is not None:
            try:
                self._hl = SyntaxHighlighter(self.sql_input.document(), 'sql')
            except Exception:
                self._hl = None
        sql_layout.addWidget(self.sql_input)
        splitter.addWidget(sql_box)

        res_box = QWidget()
        res_layout = QVBoxLayout(res_box)
        res_layout.setContentsMargins(0, 0, 0, 0)
        res_layout.addWidget(QLabel("結果 / プレビュー:"))
        self.result_view = QTextEdit()
        self.result_view.setReadOnly(True)
        self.result_view.setFont(QFont("Consolas", 10))
        res_layout.addWidget(self.result_view)
        splitter.addWidget(res_box)
        splitter.setSizes([320, 220])
        root.addWidget(splitter, 1)

        # 実行ボタン行
        btn_row = QHBoxLayout()
        self.dry_run_chk = QCheckBox("ドライラン (生成スクリプトのみ表示)")
        btn_row.addWidget(self.dry_run_chk)
        btn_row.addStretch()

        self.preview_btn = QPushButton("影響行プレビュー")
        self.preview_btn.setToolTip("UPDATE/DELETE の WHERE 条件で対象件数を COUNT します")
        self.preview_btn.clicked.connect(self._preview_impact)
        btn_row.addWidget(self.preview_btn)

        self.run_btn = QPushButton("▶ 実行 (Ctrl+Enter)")
        self.run_btn.setMinimumWidth(160)
        self.run_btn.setMinimumHeight(34)
        f = self.run_btn.font(); f.setBold(True); self.run_btn.setFont(f)
        self.run_btn.setStyleSheet(
            "QPushButton { background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            " stop:0 #e57373, stop:1 #c62828); color:#fff;"
            " border:1px solid #8e0000; border-radius:4px; padding:4px 18px; }"
            "QPushButton:hover { background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            " stop:0 #ef9a9a, stop:1 #d32f2f); }"
            "QPushButton:disabled { background:#555; color:#aaa; }")
        self.run_btn.clicked.connect(self._execute)
        btn_row.addWidget(self.run_btn)
        root.addLayout(btn_row)

        sc = QShortcut(QKeySequence("Ctrl+Return"), self)
        sc.activated.connect(self._execute)
        sc2 = QShortcut(QKeySequence("Ctrl+Enter"), self)
        sc2.activated.connect(self._execute)

    # ── プロファイル/プリセット ────────────────────────────────────────
    def _refresh_profiles(self):
        self._profiles = _load_db_profiles()
        cur = self.profile_combo.currentText()
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        for name in self._profiles:
            self.profile_combo.addItem(name)
        if cur:
            idx = self.profile_combo.findText(cur)
            if idx >= 0:
                self.profile_combo.setCurrentIndex(idx)
        self.profile_combo.blockSignals(False)
        self._on_profile_changed(self.profile_combo.currentText())

    def _on_profile_changed(self, name: str):
        prof = self._profiles.get(name, {})
        # 編集テンプレートはプロファイル別キー db_edit_cmd に保存
        tmpl = prof.get('db_edit_cmd', '')
        self.cmd_input.setPlainText(tmpl)
        self.allow_edit_chk.blockSignals(True)
        self.allow_edit_chk.setChecked(bool(prof.get('db_edit_allowed', False)))
        self.allow_edit_chk.blockSignals(False)

    def _on_preset_changed(self, idx: int):
        name = self.preset_combo.currentText()
        tmpl = _DB_EDIT_PRESETS.get(name)
        if tmpl:
            self.cmd_input.setPlainText(tmpl)
            if not self.cmd_input.isVisible():
                self.cmd_toggle.setChecked(True)
                self._toggle_cmd()

    def _toggle_cmd(self):
        vis = self.cmd_toggle.isChecked()
        self.cmd_input.setVisible(vis)
        self.save_cmd_btn.setVisible(vis)
        self.cmd_toggle.setText(("▼ " if vis else "▶ ") + "DB実行コマンド設定")

    def _save_cmd(self):
        name = self.profile_combo.currentText()
        if not name or name not in self._profiles:
            QMessageBox.warning(self, "プロファイル未選択", "保存先のプロファイルを選択してください。")
            return
        self._profiles[name]['db_edit_cmd'] = self.cmd_input.toPlainText()
        _save_db_profiles(self._profiles)
        QMessageBox.information(self, "保存", f"'{name}' に編集コマンドを保存しました。")

    def _on_allow_edit_changed(self):
        name = self.profile_combo.currentText()
        if name and name in self._profiles:
            self._profiles[name]['db_edit_allowed'] = self.allow_edit_chk.isChecked()
            _save_db_profiles(self._profiles)

    # ── 実行コマンド本体の生成 ──────────────────────────────────────────
    def _build_cmd_body(self, sql: str) -> str | None:
        cmd_template = self.cmd_input.toPlainText().strip()
        if not cmd_template:
            QMessageBox.warning(self, "コマンド未設定",
                "DB実行コマンドテンプレートを設定してください (DBプリセットから選択可)。")
            return None
        if '{SQL}' not in cmd_template:
            QMessageBox.warning(self, "テンプレートエラー",
                "テンプレートに {SQL} プレースホルダーが含まれていません。")
            return None
        # 改行正規化 + heredoc の安全弁 (<<EOF を <<'EOF' に補正)
        s = sql.replace('\r\n', '\n').replace('\r', '\n')
        cmd_body = cmd_template.replace('{SQL}', s)
        cmd_body = cmd_body.replace('\r\n', '\n').replace('\r', '\n')
        cmd_body = re.sub(
            r'(<<-?)([A-Za-z_][A-Za-z0-9_]*)(\s*\n)',
            lambda m: f"{m.group(1)}'{m.group(2)}'{m.group(3)}", cmd_body)
        return cmd_body

    # ── 影響行プレビュー ─────────────────────────────────────────────────
    def _preview_impact(self):
        sql = self.sql_input.toPlainText().strip()
        if not sql:
            QMessageBox.warning(self, "SQL 未入力", "SQL を入力してください。")
            return
        statements = _split_statements(sql)
        counts = [_build_count_query(st) for st in statements]
        counts = [c for c in counts if c]
        if not counts:
            QMessageBox.information(self, "プレビュー不可",
                "WHERE 句付きの UPDATE/DELETE が見つからないため影響行数を算出できません。")
            return
        count_sql = ";\n".join(counts) + ";"
        cmd_body = self._build_cmd_body(count_sql)
        if cmd_body is None:
            return
        prof = self._profiles.get(self.profile_combo.currentText())
        if not prof:
            QMessageBox.warning(self, "プロファイル未選択", "接続プロファイルを選択してください。")
            return
        self._mode = 'count'
        self._run_async(prof, cmd_body, "影響行プレビュー実行中...")

    # ── 実行 ─────────────────────────────────────────────────────────────
    def _execute(self):
        sql = self.sql_input.toPlainText().strip()
        if not sql:
            QMessageBox.warning(self, "SQL 未入力", "SQL を入力してください。")
            return

        kind, notes = _classify(sql)
        if kind == 'empty':
            QMessageBox.warning(self, "SQL 未入力", "有効な SQL がありません。")
            return

        is_edit = (kind == 'edit')
        prof_name = self.profile_combo.currentText()
        prof = self._profiles.get(prof_name)

        # 編集系は「このプロファイルで編集を許可」が必須
        if is_edit and not self.allow_edit_chk.isChecked():
            QMessageBox.critical(self, "編集が許可されていません",
                "⛔ このプロファイルでは更新系 SQL の実行が許可されていません。\n\n"
                "本番への誤実行防止のため、更新を行う場合は\n"
                "『このプロファイルで編集を許可』を明示的に ON にしてください。")
            return

        cmd_body = self._build_cmd_body(sql.rstrip(';') if not is_edit else sql)
        if cmd_body is None:
            return

        if self.dry_run_chk.isChecked():
            self.result_view.setPlainText(
                "[DRY RUN] 実行方式: SFTP 一時スクリプト + bash --login\n\n"
                "#!/bin/bash --login\nset -o pipefail\n"
                f"{cmd_body}\n")
            self._status("ドライラン完了")
            return

        if not prof:
            QMessageBox.warning(self, "プロファイル未選択", "接続プロファイルを選択してください。")
            return

        # 編集系は最終確認 (影響行数も可能なら添える)
        if is_edit:
            count_lines = []
            for st in _split_statements(sql):
                cq = _build_count_query(st)
                if cq:
                    count_lines.append(f"  ・{cq}")
            msg = "以下の更新系 SQL を実行します。よろしいですか？\n\n" + sql.strip()
            if notes:
                msg += "\n\n" + "\n".join(notes)
            if count_lines:
                msg += ("\n\n影響行数は『影響行プレビュー』ボタンで事前確認できます。\n"
                        "対象 (COUNT 用に変換):\n" + "\n".join(count_lines))
            msg += "\n\nテンプレートにより COMMIT され、失敗時は ROLLBACK されます。"
            r = QMessageBox.question(
                self, "実行確認", msg,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if r != QMessageBox.StandardButton.Yes:
                self._status("キャンセルしました")
                return

        self._mode = 'exec'
        self._pending_sql = sql
        self._pending_profile = prof_name
        self._run_async(prof, cmd_body, f"実行中: {prof_name} ...")

    # ── 非同期実行の共通処理 ────────────────────────────────────────────
    def _run_async(self, prof: dict, cmd_body: str, status: str):
        if SSHConnection is None and 'paramiko' not in sys.modules:
            # 接続層の存在確認 (実体は worker 内で import)
            pass
        self.run_btn.setEnabled(False)
        self.preview_btn.setEnabled(False)
        self._status(status)
        self.result_view.setPlainText(f"-- {status} --\n")
        self._worker = _ExecWorker(prof, cmd_body, self)
        self._worker.finished_ok.connect(self._on_exec_done)
        self._worker.failed.connect(self._on_exec_failed)
        self._worker.start()

    def _on_exec_done(self, out: str, err: str, exit_code: int):
        self.run_btn.setEnabled(True)
        self.preview_btn.setEnabled(True)
        parts = []
        if out.strip():
            parts.append(out.rstrip())
        if err.strip():
            parts.append("\n-- [STDERR] --\n" + err.rstrip())
        parts.append(f"\n-- exit code: {exit_code} --")
        self.result_view.setPlainText("\n".join(parts) if parts else "(出力なし)")

        if self._mode == 'exec':
            status = "成功" if exit_code == 0 else f"失敗(exit={exit_code})"
            _append_audit(getattr(self, '_pending_profile', ''),
                          self._pending_sql, status,
                          detail=(err.strip().splitlines()[0] if err.strip() else ''))
            self._status(
                f"完了 (exit={exit_code})" if exit_code == 0
                else f"エラー (exit={exit_code}) — ROLLBACK された可能性があります")
        else:
            self._status(f"プレビュー完了 (exit={exit_code})")

    def _on_exec_failed(self, msg: str):
        self.run_btn.setEnabled(True)
        self.preview_btn.setEnabled(True)
        self.result_view.setPlainText(f"接続/実行エラー:\n{msg}")
        if self._mode == 'exec':
            _append_audit(getattr(self, '_pending_profile', ''),
                          self._pending_sql, "接続エラー", detail=msg)
        self._status("エラー")

    def _status(self, text: str):
        win = self.window()
        if isinstance(win, QMainWindow):
            win.statusBar().showMessage(text)


# ---------------------------------------------------------------------------
# メインウィンドウ
# ---------------------------------------------------------------------------

class DBEditorWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"DB Editor v{__version__} — SSH経由DB編集ツール")
        self.resize(1000, 720)

        th = _theme()
        self.setStyleSheet(
            f"QMainWindow, QWidget {{ background:{th.get('bg', '#2b2b2b')};"
            f" color:{th.get('text', '#dcdcdc')}; }}")

        tabs = QTabWidget()
        self.sql_tab = SqlEditTab()
        tabs.addTab(self.sql_tab, "SQL 実行")

        # Phase 2: グリッド編集タブ (プレースホルダ)
        grid_placeholder = QWidget()
        gl = QVBoxLayout(grid_placeholder)
        lbl = QLabel(
            "グリッド編集タブは Phase 2 で実装予定です。\n\n"
            "SELECT 結果を表で表示し、セルを直接編集 → 主キーから UPDATE を\n"
            "自動生成 → ステージング → 一括コミット する機能を提供します。")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        gl.addWidget(lbl)
        tabs.addTab(grid_placeholder, "グリッド編集 (Phase 2)")

        self.setCentralWidget(tabs)
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage(
            f"プロファイルは {os.path.basename(_DB_PROFILES_PATH)} を共有 / "
            f"監査ログ: {_AUDIT_LOG_PATH}")


def main():
    app = QApplication(sys.argv)
    win = DBEditorWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
