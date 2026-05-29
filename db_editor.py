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
    QTabWidget, QStatusBar, QSplitter, QLineEdit, QTableWidget, QTableWidgetItem,
    QHeaderView, QDialog, QListWidget, QListWidgetItem,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QShortcut, QKeySequence, QColor

# ── 既存資産の流用 (失敗してもツール自体は最低限動くようフォールバック) ──────
try:
    from ssh_log_viewer import SSHConnection  # 接続層を再利用 (intent: 既存SSH接続)
except Exception:  # pragma: no cover - 単体起動時の保険
    SSHConnection = None

try:
    from text_editor import (
        SyntaxHighlighter, _theme, _DB_PROFILES_PATH,
        _load_db_profiles, _save_db_profiles,
        _DB_CMD_PRESETS, _clean_sqlplus_output,
    )
except Exception:  # pragma: no cover
    SyntaxHighlighter = None
    _DB_PROFILES_PATH = os.path.join(os.path.expanduser('~'),
                                     '.ssh_log_viewer_profiles.json')
    # 参照(SELECT)用 CSV 出力テンプレート (text_editor 流用失敗時のフォールバック)
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
        "SQLite":         'sqlite3 -header -csv /path/to/db.sqlite "{SQL}"',
        "SQL Server (sqlcmd)": 'sqlcmd -S localhost -U USER -P PASS -d DBNAME -Q "{SQL}"',
    }

    def _clean_sqlplus_output(text: str) -> str:
        return text

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
# SQL 実行履歴 (呼び戻し用)。監査ログ (append-only の証跡) とは別物。
_HISTORY_PATH = os.path.join(os.path.expanduser('~'), '.db_editor_history.json')
_HISTORY_MAX = 200

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


def _parse_csv_lines(text: str) -> list[list[str]]:
    """SELECT 出力 (CSV / 固定幅) を行列にパースする (text_editor の手法を踏襲)。"""
    import csv
    from io import StringIO
    if not text or not text.strip():
        return []
    lines = text.splitlines()
    first = 0
    for i, line in enumerate(lines):
        s = line.strip()
        if not s or s.startswith('--'):
            continue
        if s.startswith('(') and s.endswith(')'):
            continue
        first = i
        break
    clean = '\n'.join(lines[first:])
    if not clean.strip():
        return []
    if clean.count(',') >= 1:
        try:
            rows = [r for r in csv.reader(StringIO(clean)) if r]
            if max((len(r) for r in rows), default=0) >= 2:
                return rows
        except Exception:
            pass
    rows = []
    for line in clean.splitlines():
        if line.strip():
            rows.append(re.split(r' {2,}|\t+', line.strip()))
    return rows


def _sql_literal(text: str, empty_as_null: bool = True) -> str:
    """セル値を SQL リテラルに変換する。
    - None / (空欄 かつ empty_as_null) / 'NULL' トークン → NULL
    - それ以外 → シングルクォートで囲み '' エスケープ (型は暗黙変換に任せる)
    """
    if text is None:
        return 'NULL'
    s = str(text)
    if s.strip().upper() == 'NULL':
        return 'NULL'
    if s == '' and empty_as_null:
        return 'NULL'
    return "'" + s.replace("'", "''") + "'"


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


def _load_history() -> list[dict]:
    """SQL 実行履歴を読み込む (新しいものが先頭)。"""
    try:
        with open(_HISTORY_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_history(hist: list[dict]):
    try:
        with open(_HISTORY_PATH, 'w', encoding='utf-8') as f:
            json.dump(hist[:_HISTORY_MAX], f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _append_history(profile: str, sql: str, kind: str, status: str):
    """実行した SQL を履歴に追加する (新しいものが先頭、上限 _HISTORY_MAX 件)。
    kind: 'sql' (SQL実行タブ) / 'grid' (グリッド編集の適用)
    """
    sql = (sql or '').strip()
    if not sql:
        return
    hist = _load_history()
    entry = {
        'ts': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'profile': profile, 'kind': kind, 'status': status, 'sql': sql,
    }
    # 直近と同一 SQL/プロファイルの連続実行はステータスのみ更新 (重複抑制)
    if hist and hist[0].get('sql') == sql and hist[0].get('profile') == profile:
        hist[0] = entry
    else:
        hist.insert(0, entry)
    _save_history(hist)


# ---------------------------------------------------------------------------
# SQL 履歴ダイアログ
# ---------------------------------------------------------------------------

class HistoryDialog(QDialog):
    """実行済み SQL の履歴一覧。選択して SQL タブのエディタに呼び戻せる。"""

    sql_chosen = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("SQL 実行履歴")
        self.resize(820, 560)
        self.setWindowFlags(
            self.windowFlags()
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint)
        th = _theme()
        self.setStyleSheet(
            f"QDialog, QWidget {{ background:{th.get('bg', '#2b2b2b')};"
            f" color:{th.get('text', '#dcdcdc')}; }}")
        self._build_ui()
        self._reload()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.addWidget(QLabel(f"履歴ファイル: {_HISTORY_PATH} (上限 {_HISTORY_MAX} 件)"))

        splitter = QSplitter(Qt.Orientation.Vertical)
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self._on_select)
        self.list.itemDoubleClicked.connect(lambda _it: self._load_selected())
        splitter.addWidget(self.list)
        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setFont(QFont("Consolas", 10))
        splitter.addWidget(self.preview)
        splitter.setSizes([360, 180])
        root.addWidget(splitter, 1)

        btn_row = QHBoxLayout()
        self.reload_btn = QPushButton("再読込")
        self.reload_btn.clicked.connect(self._reload)
        btn_row.addWidget(self.reload_btn)
        self.clear_btn = QPushButton("履歴をクリア")
        self.clear_btn.clicked.connect(self._clear)
        btn_row.addWidget(self.clear_btn)
        btn_row.addStretch()
        self.load_btn = QPushButton("エディタに読み込む")
        self.load_btn.clicked.connect(self._load_selected)
        btn_row.addWidget(self.load_btn)
        close_btn = QPushButton("閉じる")
        close_btn.clicked.connect(self.reject)
        btn_row.addWidget(close_btn)
        root.addLayout(btn_row)

    def _reload(self):
        self._hist = _load_history()
        self.list.clear()
        for e in self._hist:
            first_line = (e.get('sql', '').strip().splitlines() or [''])[0]
            if len(first_line) > 80:
                first_line = first_line[:80] + ' …'
            kind = {'sql': 'SQL', 'grid': 'GRID'}.get(e.get('kind', ''), e.get('kind', ''))
            label = (f"[{e.get('ts', '')}] {kind} · {e.get('profile', '')} · "
                     f"{e.get('status', '')}\n    {first_line}")
            self.list.addItem(QListWidgetItem(label))
        self.preview.clear()
        if self._hist:
            self.list.setCurrentRow(0)

    def _on_select(self, row: int):
        if 0 <= row < len(self._hist):
            self.preview.setPlainText(self._hist[row].get('sql', ''))

    def _load_selected(self):
        row = self.list.currentRow()
        if 0 <= row < len(self._hist):
            self.sql_chosen.emit(self._hist[row].get('sql', ''))
            self.accept()

    def _clear(self):
        if not self._hist:
            return
        r = QMessageBox.question(
            self, "履歴クリア", "SQL 実行履歴をすべて削除しますか？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if r == QMessageBox.StandardButton.Yes:
            _save_history([])
            self._reload()


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

        self.history_btn = QPushButton("履歴")
        self.history_btn.setToolTip("過去に実行した SQL の一覧を開き、選んでエディタに呼び戻します")
        self.history_btn.clicked.connect(self._open_history)
        btn_row.addWidget(self.history_btn)

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
            _append_history(getattr(self, '_pending_profile', ''),
                            self._pending_sql, 'sql', status)
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
            _append_history(getattr(self, '_pending_profile', ''),
                            self._pending_sql, 'sql', "接続エラー")
        self._status("エラー")

    def _open_history(self):
        dlg = HistoryDialog(self)
        dlg.sql_chosen.connect(self._load_from_history)
        dlg.exec()

    def _load_from_history(self, sql: str):
        self.sql_input.setPlainText(sql)
        self._status("履歴から SQL を読み込みました")

    def _status(self, text: str):
        win = self.window()
        if isinstance(win, QMainWindow):
            win.statusBar().showMessage(text)


# ---------------------------------------------------------------------------
# グリッド編集タブ (Phase 2)
# ---------------------------------------------------------------------------

class GridEditTab(QWidget):
    """SELECT 結果を表で表示 → セル編集 → 主キーから UPDATE 自動生成 →
    ステージング → 一括コミット。

    - SELECT は参照用テンプレート (CSV出力) で実行 (プロファイルの db_cmd を流用)
    - 編集適用は編集用テンプレート (BEGIN..COMMIT) で実行 (db_edit_cmd を流用)
    - 変更は表内にステージングされ、「変更を適用」で 1 トランザクション送信
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._profiles = _load_db_profiles()
        self._worker = None
        self._mode = None              # 'select' / 'apply'
        self._header: list[str] = []
        self._original: list[list[str]] = []   # 取得直後の値スナップショット
        self._dirty: set[tuple[int, int]] = set()
        self._pending_sql = ''
        self._pending_profile = ''
        self._build_ui()
        self._refresh_profiles()

    # ── UI 構築 ──────────────────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        top = QHBoxLayout()
        top.addWidget(QLabel("接続プロファイル:"))
        self.profile_combo = QComboBox()
        self.profile_combo.setMinimumWidth(200)
        self.profile_combo.currentTextChanged.connect(self._on_profile_changed)
        top.addWidget(self.profile_combo)
        top.addSpacing(8)
        self.tmpl_toggle = QPushButton("▶ コマンドテンプレート設定")
        self.tmpl_toggle.setCheckable(True)
        self.tmpl_toggle.clicked.connect(self._toggle_tmpl)
        top.addWidget(self.tmpl_toggle)
        top.addStretch()
        self.allow_edit_chk = QCheckBox("このプロファイルで編集を許可")
        self.allow_edit_chk.setToolTip(
            "OFF の間は『変更を適用』をブロックします (本番誤実行防止)。")
        self.allow_edit_chk.stateChanged.connect(self._on_allow_edit_changed)
        top.addWidget(self.allow_edit_chk)
        root.addLayout(top)

        # テンプレート設定 (折りたたみ): SELECT用 / 編集用
        self.tmpl_box = QWidget()
        tb = QVBoxLayout(self.tmpl_box)
        tb.setContentsMargins(0, 0, 0, 0)
        tb.setSpacing(2)
        sel_row = QHBoxLayout()
        sel_row.addWidget(QLabel("SELECT用 (CSV出力):"))
        self.sel_preset = QComboBox()
        self.sel_preset.addItem("（プリセット）")
        for name in _DB_CMD_PRESETS:
            self.sel_preset.addItem(name)
        self.sel_preset.currentIndexChanged.connect(
            lambda: self._apply_preset(self.sel_preset, _DB_CMD_PRESETS, self.sel_cmd))
        sel_row.addWidget(self.sel_preset)
        sel_row.addStretch()
        tb.addLayout(sel_row)
        self.sel_cmd = QPlainTextEdit()
        self.sel_cmd.setFont(QFont("Consolas", 9))
        self.sel_cmd.setMaximumHeight(80)
        self.sel_cmd.setPlaceholderText("SELECT を CSV (1行目=ヘッダー) で返すテンプレート。{SQL} を置換。")
        tb.addWidget(self.sel_cmd)

        edit_row = QHBoxLayout()
        edit_row.addWidget(QLabel("編集用 (BEGIN..COMMIT):"))
        self.edit_preset = QComboBox()
        self.edit_preset.addItem("（プリセット）")
        for name in _DB_EDIT_PRESETS:
            self.edit_preset.addItem(name)
        self.edit_preset.currentIndexChanged.connect(
            lambda: self._apply_preset(self.edit_preset, _DB_EDIT_PRESETS, self.edit_cmd))
        edit_row.addWidget(self.edit_preset)
        edit_row.addStretch()
        self.save_tmpl_btn = QPushButton("テンプレートをプロファイルに保存")
        self.save_tmpl_btn.clicked.connect(self._save_templates)
        edit_row.addWidget(self.save_tmpl_btn)
        tb.addLayout(edit_row)
        self.edit_cmd = QPlainTextEdit()
        self.edit_cmd.setFont(QFont("Consolas", 9))
        self.edit_cmd.setMaximumHeight(80)
        self.edit_cmd.setPlaceholderText("UPDATE 群を流す編集テンプレート。{SQL} を置換。")
        tb.addWidget(self.edit_cmd)
        self.tmpl_box.setVisible(False)
        root.addWidget(self.tmpl_box)

        # テーブル名 / 主キー / SELECT 入力
        meta = QHBoxLayout()
        meta.addWidget(QLabel("テーブル:"))
        self.table_input = QLineEdit()
        self.table_input.setPlaceholderText("例: SCOTT.EMP")
        self.table_input.setMaximumWidth(220)
        meta.addWidget(self.table_input)
        meta.addWidget(QLabel("主キー列 (, 区切り):"))
        self.pk_input = QLineEdit()
        self.pk_input.setPlaceholderText("例: EMPNO  /  ID,SUB_ID")
        self.pk_input.setMaximumWidth(220)
        meta.addWidget(self.pk_input)
        self.empty_null_chk = QCheckBox("空欄を NULL にする")
        self.empty_null_chk.setChecked(True)
        meta.addWidget(self.empty_null_chk)
        meta.addStretch()
        root.addLayout(meta)

        sql_row = QHBoxLayout()
        sql_row.addWidget(QLabel("SELECT 文:"))
        self.fetch_btn = QPushButton("データ取得")
        self.fetch_btn.clicked.connect(self._fetch)
        sql_row.addStretch()
        sql_row.addWidget(self.fetch_btn)
        root.addLayout(sql_row)
        self.sql_input = QPlainTextEdit()
        self.sql_input.setFont(QFont("Consolas", 10))
        self.sql_input.setMaximumHeight(80)
        self.sql_input.setPlaceholderText("例: SELECT EMPNO, ENAME, SAL FROM SCOTT.EMP WHERE DEPTNO = 10")
        if SyntaxHighlighter is not None:
            try:
                self._hl = SyntaxHighlighter(self.sql_input.document(), 'sql')
            except Exception:
                self._hl = None
        root.addWidget(self.sql_input)

        # グリッド + 結果ログのスプリッタ
        splitter = QSplitter(Qt.Orientation.Vertical)
        self.table = QTableWidget()
        self.table.setEditTriggers(
            QTableWidget.EditTrigger.DoubleClicked
            | QTableWidget.EditTrigger.SelectedClicked
            | QTableWidget.EditTrigger.EditKeyPressed)
        self.table.itemChanged.connect(self._on_item_changed)
        splitter.addWidget(self.table)
        self.result_view = QTextEdit()
        self.result_view.setReadOnly(True)
        self.result_view.setFont(QFont("Consolas", 9))
        self.result_view.setMaximumHeight(160)
        splitter.addWidget(self.result_view)
        splitter.setSizes([420, 140])
        root.addWidget(splitter, 1)

        # 操作ボタン
        btn_row = QHBoxLayout()
        self.dirty_lbl = QLabel("変更: 0 セル")
        btn_row.addWidget(self.dirty_lbl)
        btn_row.addStretch()
        self.revert_btn = QPushButton("変更を破棄")
        self.revert_btn.clicked.connect(self._revert)
        btn_row.addWidget(self.revert_btn)
        self.preview_btn = QPushButton("変更をプレビュー (UPDATE生成)")
        self.preview_btn.clicked.connect(self._preview)
        btn_row.addWidget(self.preview_btn)
        self.apply_btn = QPushButton("▶ 変更を適用")
        self.apply_btn.setMinimumHeight(32)
        f = self.apply_btn.font(); f.setBold(True); self.apply_btn.setFont(f)
        self.apply_btn.setStyleSheet(
            "QPushButton { background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            " stop:0 #e57373, stop:1 #c62828); color:#fff;"
            " border:1px solid #8e0000; border-radius:4px; padding:4px 16px; }"
            "QPushButton:hover { background:#d32f2f; }"
            "QPushButton:disabled { background:#555; color:#aaa; }")
        self.apply_btn.clicked.connect(self._apply)
        btn_row.addWidget(self.apply_btn)
        root.addLayout(btn_row)

    # ── プロファイル / テンプレート ─────────────────────────────────────
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
        self.sel_cmd.setPlainText(prof.get('db_cmd', ''))
        self.edit_cmd.setPlainText(prof.get('db_edit_cmd', ''))
        self.allow_edit_chk.blockSignals(True)
        self.allow_edit_chk.setChecked(bool(prof.get('db_edit_allowed', False)))
        self.allow_edit_chk.blockSignals(False)

    def _apply_preset(self, combo, presets, target):
        tmpl = presets.get(combo.currentText())
        if tmpl:
            target.setPlainText(tmpl)

    def _toggle_tmpl(self):
        vis = self.tmpl_toggle.isChecked()
        self.tmpl_box.setVisible(vis)
        self.tmpl_toggle.setText(("▼ " if vis else "▶ ") + "コマンドテンプレート設定")

    def _save_templates(self):
        name = self.profile_combo.currentText()
        if not name or name not in self._profiles:
            QMessageBox.warning(self, "プロファイル未選択", "保存先のプロファイルを選択してください。")
            return
        self._profiles[name]['db_cmd'] = self.sel_cmd.toPlainText()
        self._profiles[name]['db_edit_cmd'] = self.edit_cmd.toPlainText()
        _save_db_profiles(self._profiles)
        QMessageBox.information(self, "保存", f"'{name}' にテンプレートを保存しました。")

    def _on_allow_edit_changed(self):
        name = self.profile_combo.currentText()
        if name and name in self._profiles:
            self._profiles[name]['db_edit_allowed'] = self.allow_edit_chk.isChecked()
            _save_db_profiles(self._profiles)

    def _build_cmd_body(self, template: str, sql: str) -> str | None:
        template = template.strip()
        if not template:
            QMessageBox.warning(self, "コマンド未設定",
                "テンプレートが未設定です。『コマンドテンプレート設定』で選択/保存してください。")
            return None
        if '{SQL}' not in template:
            QMessageBox.warning(self, "テンプレートエラー", "テンプレートに {SQL} がありません。")
            return None
        s = sql.replace('\r\n', '\n').replace('\r', '\n')
        body = template.replace('{SQL}', s).replace('\r\n', '\n').replace('\r', '\n')
        body = re.sub(r'(<<-?)([A-Za-z_][A-Za-z0-9_]*)(\s*\n)',
                      lambda m: f"{m.group(1)}'{m.group(2)}'{m.group(3)}", body)
        return body

    # ── データ取得 (SELECT) ─────────────────────────────────────────────
    def _fetch(self):
        sql = self.sql_input.toPlainText().strip().rstrip(';')
        if not sql:
            QMessageBox.warning(self, "SQL 未入力", "SELECT 文を入力してください。")
            return
        if _first_keyword(sql) not in _READ_ONLY_KEYWORDS:
            QMessageBox.warning(self, "SELECT のみ",
                "データ取得は参照系 (SELECT/WITH 等) のみ可能です。")
            return
        prof = self._profiles.get(self.profile_combo.currentText())
        if not prof:
            QMessageBox.warning(self, "プロファイル未選択", "接続プロファイルを選択してください。")
            return
        body = self._build_cmd_body(self.sel_cmd.toPlainText(), sql)
        if body is None:
            return
        self._mode = 'select'
        self._run_async(prof, body, "データ取得中...")

    def _populate_grid(self, csv_text: str):
        rows = _parse_csv_lines(csv_text)
        self.table.blockSignals(True)
        self.table.clear()
        self._dirty.clear()
        self._update_dirty_label()
        if not rows:
            self.table.setRowCount(0)
            self.table.setColumnCount(0)
            self._header = []
            self._original = []
            self.table.blockSignals(False)
            return
        ncols = max(len(r) for r in rows)
        header = (rows[0] + [''] * (ncols - len(rows[0])))
        self._header = [h.strip() or f"col{i+1}" for i, h in enumerate(header)]
        body = rows[1:]
        self._original = [
            [(r[c] if c < len(r) else '') for c in range(ncols)] for r in body
        ]
        self.table.setColumnCount(ncols)
        self.table.setHorizontalHeaderLabels(self._header)
        self.table.setRowCount(len(body))
        for r, row in enumerate(self._original):
            for c in range(ncols):
                self.table.setItem(r, c, QTableWidgetItem(row[c]))
        self.table.resizeColumnsToContents()
        for c in range(ncols):
            if self.table.columnWidth(c) > 360:
                self.table.setColumnWidth(c, 360)
        self.table.blockSignals(False)

    # ── セル編集の追跡 ───────────────────────────────────────────────────
    def _on_item_changed(self, item: QTableWidgetItem):
        r, c = item.row(), item.column()
        if r >= len(self._original) or c >= len(self._original[r]):
            return
        orig = self._original[r][c]
        if item.text() != orig:
            self._dirty.add((r, c))
            item.setBackground(QColor("#5a3a1a"))
        else:
            self._dirty.discard((r, c))
            item.setBackground(QColor(0, 0, 0, 0))
        self._update_dirty_label()

    def _update_dirty_label(self):
        rows = {r for r, _ in self._dirty}
        self.dirty_lbl.setText(f"変更: {len(self._dirty)} セル / {len(rows)} 行")

    def _revert(self):
        if not self._dirty:
            return
        self.table.blockSignals(True)
        for (r, c) in list(self._dirty):
            it = self.table.item(r, c)
            if it is not None:
                it.setText(self._original[r][c])
                it.setBackground(QColor(0, 0, 0, 0))
        self._dirty.clear()
        self.table.blockSignals(False)
        self._update_dirty_label()

    # ── UPDATE 生成 ──────────────────────────────────────────────────────
    def _pk_indices(self) -> list[int] | None:
        pk_raw = [p.strip() for p in self.pk_input.text().split(',') if p.strip()]
        if not pk_raw:
            QMessageBox.warning(self, "主キー未指定",
                "UPDATE の WHERE 条件に使う主キー列を指定してください。")
            return None
        lower = [h.lower() for h in self._header]
        idxs = []
        for pk in pk_raw:
            if pk.lower() not in lower:
                QMessageBox.warning(self, "主キー列が見つかりません",
                    f"列 '{pk}' は取得結果のヘッダーに存在しません。\n"
                    f"取得列: {', '.join(self._header)}")
                return None
            idxs.append(lower.index(pk.lower()))
        return idxs

    def _generate_updates(self) -> list[str] | None:
        if not self._dirty:
            return []
        table = self.table_input.text().strip()
        if not table:
            QMessageBox.warning(self, "テーブル未指定", "UPDATE 対象のテーブル名を入力してください。")
            return None
        pk_idx = self._pk_indices()
        if pk_idx is None:
            return None
        empty_null = self.empty_null_chk.isChecked()
        dirty_rows: dict[int, list[int]] = {}
        for (r, c) in self._dirty:
            dirty_rows.setdefault(r, []).append(c)
        stmts = []
        for r in sorted(dirty_rows):
            set_cols = sorted(dirty_rows[r])
            set_parts = []
            for c in set_cols:
                it = self.table.item(r, c)
                new_val = it.text() if it is not None else ''
                set_parts.append(f"{self._header[c]} = {_sql_literal(new_val, empty_null)}")
            # WHERE は取得直後の主キー値で行を特定 (主キー自体を編集していても元の行)
            where_parts = []
            for c in pk_idx:
                ov = self._original[r][c]
                where_parts.append(f"{self._header[c]} = {_sql_literal(ov, empty_null)}")
            stmts.append(
                f"UPDATE {table} SET {', '.join(set_parts)} "
                f"WHERE {' AND '.join(where_parts)};")
        return stmts

    def _preview(self):
        stmts = self._generate_updates()
        if stmts is None:
            return
        if not stmts:
            self.result_view.setPlainText("変更がありません。")
            return
        self.result_view.setPlainText(
            "-- 生成された UPDATE (適用前プレビュー) --\n" + "\n".join(stmts))
        self._status(f"{len(stmts)} 件の UPDATE を生成")

    def _apply(self):
        stmts = self._generate_updates()
        if stmts is None:
            return
        if not stmts:
            QMessageBox.information(self, "変更なし", "適用する変更がありません。")
            return
        if not self.allow_edit_chk.isChecked():
            QMessageBox.critical(self, "編集が許可されていません",
                "⛔ このプロファイルでは編集が許可されていません。\n"
                "『このプロファイルで編集を許可』を ON にしてください。")
            return
        prof = self._profiles.get(self.profile_combo.currentText())
        if not prof:
            QMessageBox.warning(self, "プロファイル未選択", "接続プロファイルを選択してください。")
            return
        sql = "\n".join(stmts)
        body = self._build_cmd_body(self.edit_cmd.toPlainText(), sql)
        if body is None:
            return
        rows = {r for r, _ in self._dirty}
        r = QMessageBox.question(
            self, "適用確認",
            f"{len(rows)} 行 / {len(self._dirty)} セルの変更を適用します。\n\n"
            f"{sql}\n\n1 トランザクションで COMMIT され、失敗時は ROLLBACK されます。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if r != QMessageBox.StandardButton.Yes:
            self._status("キャンセルしました")
            return
        self._mode = 'apply'
        self._pending_sql = sql
        self._pending_profile = self.profile_combo.currentText()
        self._run_async(prof, body, "変更を適用中...")

    # ── 非同期実行 ───────────────────────────────────────────────────────
    def _run_async(self, prof: dict, body: str, status: str):
        self.fetch_btn.setEnabled(False)
        self.apply_btn.setEnabled(False)
        self.preview_btn.setEnabled(False)
        self._status(status)
        self._worker = _ExecWorker(prof, body, self)
        self._worker.finished_ok.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_done(self, out: str, err: str, exit_code: int):
        self.fetch_btn.setEnabled(True)
        self.apply_btn.setEnabled(True)
        self.preview_btn.setEnabled(True)
        if self._mode == 'select':
            clean = _clean_sqlplus_output(out)
            self._populate_grid(clean)
            log = []
            if err.strip():
                log.append("-- [STDERR] --\n" + err.rstrip())
            log.append(f"-- 取得完了 (exit={exit_code}), {self.table.rowCount()} 行 --")
            self.result_view.setPlainText("\n".join(log))
            self._status(f"取得 {self.table.rowCount()} 行 (exit={exit_code})")
        else:  # apply
            parts = []
            if out.strip():
                parts.append(out.rstrip())
            if err.strip():
                parts.append("\n-- [STDERR] --\n" + err.rstrip())
            parts.append(f"\n-- exit code: {exit_code} --")
            self.result_view.setPlainText("\n".join(parts))
            status = "成功" if exit_code == 0 else f"失敗(exit={exit_code})"
            _append_audit(self._pending_profile, self._pending_sql, status,
                          detail=(err.strip().splitlines()[0] if err.strip() else ''))
            _append_history(self._pending_profile, self._pending_sql, 'grid', status)
            if exit_code == 0:
                # 適用成功: 現在のセル値を新しい original として確定し dirty をクリア
                self.table.blockSignals(True)
                for (r, c) in list(self._dirty):
                    it = self.table.item(r, c)
                    if it is not None:
                        self._original[r][c] = it.text()
                        it.setBackground(QColor(0, 0, 0, 0))
                self._dirty.clear()
                self.table.blockSignals(False)
                self._update_dirty_label()
                self._status("適用成功 (COMMIT 済)")
            else:
                self._status(f"適用エラー (exit={exit_code}) — ROLLBACK の可能性")

    def _on_failed(self, msg: str):
        self.fetch_btn.setEnabled(True)
        self.apply_btn.setEnabled(True)
        self.preview_btn.setEnabled(True)
        self.result_view.setPlainText(f"接続/実行エラー:\n{msg}")
        if self._mode == 'apply':
            _append_audit(self._pending_profile, self._pending_sql, "接続エラー", detail=msg)
            _append_history(self._pending_profile, self._pending_sql, 'grid', "接続エラー")
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
        self.grid_tab = GridEditTab()
        tabs.addTab(self.grid_tab, "グリッド編集")

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
