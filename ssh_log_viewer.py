#!/usr/bin/env python3
"""SSH/Telnet Log Viewer — マルチサーバー・グリッドログ解析ツール"""
__version__ = "1.1.8"

import sys, os, re, json, stat as stat_mod, time, socket, select

try:
    import paramiko
except ImportError:
    print("paramiko が必要です: pip install paramiko")
    sys.exit(1)

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QPlainTextEdit, QLabel, QLineEdit, QPushButton, QComboBox,
    QTreeWidget, QTreeWidgetItem, QDialog, QGridLayout, QFileDialog,
    QMessageBox, QInputDialog, QCheckBox, QFrame, QToolBar, QSizePolicy,
    QListWidget, QListWidgetItem, QTabWidget,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize, QTimer
from PyQt6.QtGui import (
    QFont, QColor, QTextCharFormat, QSyntaxHighlighter,
    QAction, QKeySequence, QTextCursor,
)


# ---------------------------------------------------------------------------
# サーバーカラーパレット（最大6サーバー）
# ---------------------------------------------------------------------------

# ダーク用: 暗背景 + 明るいアクセント文字
_PALETTES_DARK = [
    ('#0D2137', '#7FC0FF'),   # blue   (was #4A9EFF)
    ('#0D2A0D', '#80E080'),   # green  (was #5FBF5F)
    ('#2D1800', '#FFC060'),   # orange (was #E8A030)
    ('#1A0D2A', '#C8A0FF'),   # purple (was #9876CC)
    ('#2A0D0D', '#FF8095'),   # red    (was #CF6679)
    ('#1A2A2A', '#80E6D0'),   # teal   (was #4EC9B0)
]
# ライト用: 淡背景 + 濃いアクセント文字
_PALETTES_LIGHT = [
    ('#DDEAFF', '#1A4A8A'),   # blue
    ('#DDF0DD', '#2A6A2A'),   # green
    ('#FFE8CC', '#8A4A00'),   # orange
    ('#EADDF0', '#5A3A8A'),   # purple
    ('#FFD8D8', '#8A2020'),   # red
    ('#D8F0F0', '#1A6A6A'),   # teal
]


def _palette(idx: int) -> tuple[str, str]:
    """現在のテーマに応じて (bg, fg) を返す"""
    is_light = SETTINGS.get('theme', 'Dark') in ('Light', 'Solarized Light')
    pal = _PALETTES_LIGHT if is_light else _PALETTES_DARK
    return pal[idx % len(pal)]


# ---------------------------------------------------------------------------
# SSH接続プロファイル管理
# ---------------------------------------------------------------------------

_PROFILES_PATH = os.path.join(os.path.expanduser('~'), '.ssh_log_viewer_profiles.json')

def _load_profiles() -> dict:
    try:
        with open(_PROFILES_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}

def _save_profiles(profiles: dict):
    with open(_PROFILES_PATH, 'w', encoding='utf-8') as f:
        json.dump(profiles, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# アプリ設定 (フォントサイズ・テーマ)
# ---------------------------------------------------------------------------

_SETTINGS_PATH = os.path.join(os.path.expanduser('~'), '.ssh_log_viewer_settings.json')

# 暗系テーマ共通の構文配色 (白文字＝暗背景向き)
_SYNTAX_DARK = {
    'syn_timestamp': '#4EC9B0', 'syn_bracket':   '#9876AA',
    'syn_exception': '#FF7070', 'syn_stack':     '#CC7832',
    'syn_http':      '#FF7070',
    'syn_sql_kw':    '#CC7832', 'syn_sql_type':  '#4EC9B0',
    'syn_sql_func':  '#DCDCAA', 'syn_sql_str':   '#6A8759',
    'syn_sql_num':   '#6897BB', 'syn_sql_cmt':   '#808080',
}
# 明系テーマ共通の構文配色 (黒文字＝白背景向き)
_SYNTAX_LIGHT = {
    'syn_timestamp': '#007070', 'syn_bracket':   '#6F42C1',
    'syn_exception': '#A80000', 'syn_stack':     '#B45A00',
    'syn_http':      '#A80000',
    'syn_sql_kw':    '#B45A00', 'syn_sql_type':  '#007070',
    'syn_sql_func':  '#7A5500', 'syn_sql_str':   '#22863A',
    'syn_sql_num':   '#1C5BC0', 'syn_sql_cmt':   '#6A737D',
}

# テーマプリセット (背景・テキスト・選択色 + ログ表示用配色)
_THEME_PRESETS = {
    'Dark': {
        'bg':          '#1a1a1a',
        'panel_bg':    '#1e1e1e',
        'toolbar_bg':  '#252525',
        'text':        '#a9b7c6',
        'text_dim':    '#808080',
        'selection':   '#214283',
        'border':      '#333333',
        'control_bg':  '#3a3a3a',
        'control_hover': '#4a4a4a',
        'log_bg':      '#1a1a1a',
        'level_error_bg': '#3D1515', 'level_error_fg': '#FF7070',
        'level_warn_bg':  '#2D2512', 'level_warn_fg':  '#E8B26A',
        'level_info_bg':  '#1A2A1A', 'level_info_fg':  '#6A9F6A',
        'level_debug_fg': '#707070', 'level_trace_fg': '#505050',
        **_SYNTAX_DARK,
    },
    'Dark Blue': {
        'bg':          '#0e1525',
        'panel_bg':    '#131c2f',
        'toolbar_bg':  '#172238',
        'text':        '#c0d0e8',
        'text_dim':    '#7080a0',
        'selection':   '#2a4a8a',
        'border':      '#1f2d4a',
        'control_bg':  '#1f2d4a',
        'control_hover': '#2a3d60',
        'log_bg':      '#0e1525',
        'level_error_bg': '#3a1a25', 'level_error_fg': '#FF8080',
        'level_warn_bg':  '#332a12', 'level_warn_fg':  '#FFD080',
        'level_info_bg':  '#162a3a', 'level_info_fg':  '#80C0FF',
        'level_debug_fg': '#7080a0', 'level_trace_fg': '#506080',
        **_SYNTAX_DARK,
    },
    'High Contrast': {
        'bg':          '#000000',
        'panel_bg':    '#0a0a0a',
        'toolbar_bg':  '#151515',
        'text':        '#ffffff',
        'text_dim':    '#a0a0a0',
        'selection':   '#0066cc',
        'border':      '#444444',
        'control_bg':  '#2a2a2a',
        'control_hover': '#3a3a3a',
        'log_bg':      '#000000',
        'level_error_bg': '#600000', 'level_error_fg': '#FF6060',
        'level_warn_bg':  '#5a4500', 'level_warn_fg':  '#FFD060',
        'level_info_bg':  '#003a00', 'level_info_fg':  '#80FF80',
        'level_debug_fg': '#a0a0a0', 'level_trace_fg': '#707070',
        **_SYNTAX_DARK,
    },
    'Monochrome': {
        'bg':          '#1c1c1c',
        'panel_bg':    '#222222',
        'toolbar_bg':  '#2a2a2a',
        'text':        '#cccccc',
        'text_dim':    '#888888',
        'selection':   '#505050',
        'border':      '#3a3a3a',
        'control_bg':  '#3a3a3a',
        'control_hover': '#4a4a4a',
        'log_bg':      '#1c1c1c',
        'level_error_bg': '#3a3a3a', 'level_error_fg': '#ffffff',
        'level_warn_bg':  '#2f2f2f', 'level_warn_fg':  '#dddddd',
        'level_info_bg':  '#262626', 'level_info_fg':  '#aaaaaa',
        'level_debug_fg': '#888888', 'level_trace_fg': '#666666',
        **_SYNTAX_DARK,
    },
    'Light': {
        'bg':          '#f4f4f4',
        'panel_bg':    '#ffffff',
        'toolbar_bg':  '#e6e6e6',
        'text':        '#1e1e1e',
        'text_dim':    '#666666',
        'selection':   '#cfe5ff',
        'border':      '#cccccc',
        'control_bg':  '#dcdcdc',
        'control_hover': '#c8c8c8',
        'log_bg':      '#ffffff',
        'level_error_bg': '#ffe2e2', 'level_error_fg': '#a80000',
        'level_warn_bg':  '#fff4cc', 'level_warn_fg':  '#7a5500',
        'level_info_bg':  '#e6f5e6', 'level_info_fg':  '#206020',
        'level_debug_fg': '#888888', 'level_trace_fg': '#aaaaaa',
        **_SYNTAX_LIGHT,
    },
    'Solarized Light': {
        'bg':          '#fdf6e3',
        'panel_bg':    '#eee8d5',
        'toolbar_bg':  '#e4dcc3',
        'text':        '#586e75',
        'text_dim':    '#93a1a1',
        'selection':   '#cfd9c4',
        'border':      '#b8b298',
        'control_bg':  '#e4dcc3',
        'control_hover': '#d4cba8',
        'log_bg':      '#fdf6e3',
        'level_error_bg': '#fadbd8', 'level_error_fg': '#dc322f',
        'level_warn_bg':  '#fbeac0', 'level_warn_fg':  '#b58900',
        'level_info_bg':  '#dde7c8', 'level_info_fg':  '#859900',
        'level_debug_fg': '#93a1a1', 'level_trace_fg': '#b1c0c0',
        **_SYNTAX_LIGHT,
    },
}

_DEFAULT_SETTINGS = {
    'tree_font_size':     10,
    'toolbar_font_size':  11,
    'log_font_size':       9,
    'terminal_font_size': 10,
    'theme':              'Dark',
    'show_quick_jump':    True,   # 左パネルのクイックジャンプ表示
    'show_panel_hints':   True,   # 左パネルの説明ラベル表示
}


def _load_settings() -> dict:
    try:
        with open(_SETTINGS_PATH, 'r', encoding='utf-8') as f:
            loaded = json.load(f)
    except Exception:
        loaded = {}
    return {**_DEFAULT_SETTINGS, **loaded}


def _save_settings(s: dict):
    with open(_SETTINGS_PATH, 'w', encoding='utf-8') as f:
        json.dump(s, f, ensure_ascii=False, indent=2)


# モジュールグローバルとして共有
SETTINGS: dict = _load_settings()


# ---------------------------------------------------------------------------
# ワークスペース (定型ログイン構成 — 接続+開きたいログのセット)
# ---------------------------------------------------------------------------

_WORKSPACES_PATH = os.path.join(os.path.expanduser('~'), '.ssh_log_viewer_workspaces.json')


def _load_workspaces() -> dict:
    try:
        with open(_WORKSPACES_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _save_workspaces(workspaces: dict):
    with open(_WORKSPACES_PATH, 'w', encoding='utf-8') as f:
        json.dump(workspaces, f, ensure_ascii=False, indent=2)


def _theme() -> dict:
    return _THEME_PRESETS.get(SETTINGS.get('theme', 'Dark'), _THEME_PRESETS['Dark'])


# ---------------------------------------------------------------------------
# 一時ファイルクリーンアップ (「テキストエディタで開く」DL分)
# ---------------------------------------------------------------------------

_TEMP_RETENTION_DAYS = 7


def _cleanup_old_temp_files(base_dir: str, max_age_days: int = _TEMP_RETENTION_DAYS):
    """指定 dir 配下で N 日以上前のファイルを削除し、空ディレクトリも除去。"""
    if not os.path.isdir(base_dir):
        return 0
    cutoff = time.time() - max_age_days * 86400
    removed = 0
    for root, _dirs, files in os.walk(base_dir, topdown=False):
        for fname in files:
            fpath = os.path.join(root, fname)
            try:
                if os.path.getmtime(fpath) < cutoff:
                    os.remove(fpath)
                    removed += 1
            except Exception:
                pass
        try:
            if not os.listdir(root) and root != base_dir:
                os.rmdir(root)
        except Exception:
            pass
    return removed


# ---------------------------------------------------------------------------
# SSH接続クラス
# ---------------------------------------------------------------------------

class SSHConnection:
    protocol = 'ssh'

    def __init__(self):
        self.client = None
        self.sftp   = None
        self.label  = ''
        self._info  = {}

    def connect(self, host, port, user, password='', key_path=''):
        c = paramiko.SSHClient()
        c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        kw: dict = dict(hostname=host, port=port, username=user, timeout=10)
        key = key_path.strip()
        if key and os.path.exists(os.path.expanduser(key)):
            kw['key_filename'] = os.path.expanduser(key)
        if password:
            kw['password'] = password
        c.connect(**kw)
        self.client = c
        # 接続維持: 30秒毎にキープアライブパケットを送ってサーバー側の
        # idle timeout 切断を防ぐ
        try:
            tr = c.get_transport()
            if tr is not None:
                tr.set_keepalive(30)
        except Exception:
            pass
        self.sftp   = c.open_sftp()
        self.label  = f"{user}@{host}"
        self._info  = dict(host=host, port=port, user=user,
                           password=password, key_path=key_path)

    def disconnect(self):
        try:
            if self.sftp:   self.sftp.close()
            if self.client: self.client.close()
        except Exception:
            pass
        self.client = self.sftp = None

    @property
    def connected(self) -> bool:
        return self.client is not None

    def _is_transport_alive(self) -> bool:
        """SSH トランスポートが生きているかチェック。"""
        if self.client is None:
            return False
        try:
            tr = self.client.get_transport()
            return tr is not None and tr.is_active() and tr.is_alive()
        except Exception:
            return False

    def _reconnect(self):
        """保存済み接続情報で再接続する。失敗時は例外を再送出。"""
        info = dict(self._info or {})
        try:
            if self.sftp:
                self.sftp.close()
        except Exception:
            pass
        try:
            if self.client:
                self.client.close()
        except Exception:
            pass
        self.client = None
        self.sftp = None
        if not info:
            raise RuntimeError("再接続情報がありません")
        self.connect(info.get('host', ''), info.get('port', 22),
                     info.get('user', ''), info.get('password', ''),
                     info.get('key_path', ''))

    def _ensure_alive(self):
        """通信前に transport の生死を確認し、死んでいれば1回だけ自動再接続。"""
        if not self._is_transport_alive():
            self._reconnect()

    def listdir(self, path: str):
        self._ensure_alive()
        entries = self.sftp.listdir_attr(path)
        entries.sort(key=lambda a: (not stat_mod.S_ISDIR(a.st_mode), a.filename.lower()))
        return entries

    def read_tail(self, path: str, lines: int = 5000) -> str:
        self._ensure_alive()
        _, out, _ = self.client.exec_command(
            f'tail -n {lines} "{path}" 2>/dev/null || cat "{path}" 2>/dev/null'
        )
        return out.read().decode('utf-8', errors='replace')

    def exec(self, cmd: str) -> str:
        self._ensure_alive()
        _, out, _ = self.client.exec_command(cmd)
        return out.read().decode('utf-8', errors='replace')

    def open_tail_channel(self, path: str) -> '_TailChannel':
        self._ensure_alive()
        transport = self.client.get_transport()
        chan = transport.open_session()
        # -F (= --follow=name --retry): ローテーションされても同じ名前を追従
        chan.exec_command(f'tail -F "{path}"')
        return _SSHChannel(chan)

    def open_shell_channel(self) -> '_TailChannel':
        self._ensure_alive()
        chan = self.client.invoke_shell(term='xterm', width=120, height=30)
        return _SSHChannel(chan)

    def download_bytes(self, path: str) -> bytes:
        """リモートファイルを全文バイトで取得 (SFTP)。
        ソケット切断時は1回だけ自動再接続を試みる。
        """
        try:
            self._ensure_alive()
            with self.sftp.open(path, 'rb') as f:
                return f.read()
        except (EOFError, OSError, paramiko.SSHException) as e:
            # 何らかの理由で SFTP が死んでいたら再接続を1度試す
            msg = str(e).lower()
            if 'closed' in msg or 'eof' in msg or 'broken' in msg or 'not connected' in msg \
                    or isinstance(e, (EOFError, paramiko.SSHException)):
                try:
                    self._reconnect()
                    with self.sftp.open(path, 'rb') as f:
                        return f.read()
                except Exception:
                    raise
            raise


# ---------------------------------------------------------------------------
# Telnet 低レベルクライアント（Python 3.13+ で telnetlib が削除されたため自前実装）
# ---------------------------------------------------------------------------

# Telnet command bytes
_IAC, _DONT, _DO, _WONT, _WILL = 0xFF, 0xFE, 0xFD, 0xFC, 0xFB
_SB, _SE = 0xFA, 0xF0


class _TelnetClient:
    """最小限の telnet クライアント。IAC ネゴシエーションは全拒否で応答する。"""

    def __init__(self):
        self.sock: socket.socket | None = None

    def open(self, host: str, port: int = 23, timeout: float = 10):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.setblocking(False)

    def close(self):
        try:
            if self.sock:
                self.sock.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        try:
            if self.sock:
                self.sock.close()
        except Exception:
            pass
        self.sock = None

    def write(self, data: bytes):
        if not self.sock:
            return
        # ペイロード中の 0xFF はエスケープが必要
        payload = data.replace(b'\xff', b'\xff\xff')
        self.sock.setblocking(True)
        try:
            self.sock.sendall(payload)
        finally:
            self.sock.setblocking(False)

    def recv(self, timeout: float = 0.3) -> bytes:
        """IAC を処理した上で読み取れた生バイトを返す。タイムアウトしたら b''。"""
        if not self.sock:
            return b''
        r, _, _ = select.select([self.sock], [], [], timeout)
        if not r:
            return b''
        try:
            raw = self.sock.recv(4096)
        except (BlockingIOError, ConnectionResetError, OSError):
            return b''
        if not raw:
            return b''
        return self._process_iac(raw)

    def read_until(self, expected: bytes, timeout: float = 10) -> bytes:
        deadline = time.time() + timeout
        result = bytearray()
        while time.time() < deadline:
            chunk = self.recv(0.3)
            if chunk:
                result.extend(chunk)
                if expected in result:
                    break
        return bytes(result)

    def _process_iac(self, raw: bytes) -> bytes:
        """IAC コマンドを取り除き、すべてのオプション要求を拒否で応答する。"""
        out = bytearray()
        responses = bytearray()
        i, n = 0, len(raw)
        while i < n:
            b = raw[i]
            if b != _IAC:
                out.append(b)
                i += 1
                continue
            if i + 1 >= n:
                break
            cmd = raw[i + 1]
            if cmd == _IAC:
                out.append(_IAC)
                i += 2
            elif cmd in (_DO, _DONT, _WILL, _WONT):
                if i + 2 >= n:
                    break
                opt = raw[i + 2]
                if cmd == _DO:
                    responses.extend([_IAC, _WONT, opt])
                elif cmd == _WILL:
                    responses.extend([_IAC, _DONT, opt])
                i += 3
            elif cmd == _SB:
                # サブネゴシエーション: IAC SE まで読み捨て
                se = raw.find(bytes([_IAC, _SE]), i + 2)
                if se == -1:
                    break
                i = se + 2
            else:
                i += 2
        if responses and self.sock:
            self.sock.setblocking(True)
            try:
                self.sock.sendall(bytes(responses))
            except Exception:
                pass
            finally:
                self.sock.setblocking(False)
        return bytes(out)


# ---------------------------------------------------------------------------
# 擬似 stat (Telnet listdir 用 — paramiko.SFTPAttributes と互換)
# ---------------------------------------------------------------------------

class _FakeStat:
    def __init__(self, name: str, is_dir: bool):
        self.filename = name
        self.st_mode = stat_mod.S_IFDIR if is_dir else stat_mod.S_IFREG


# ---------------------------------------------------------------------------
# Telnet 接続クラス（SSHConnection と同じ API）
# ---------------------------------------------------------------------------

_TELNET_END_MARKER = '__TEL_END_OF_CMD__'


class TelnetConnection:
    protocol = 'telnet'

    def __init__(self):
        self._tn: _TelnetClient | None = None
        self.label = ''
        self._info: dict = {}

    @property
    def connected(self) -> bool:
        return self._tn is not None

    def connect(self, host, port, user, password='', key_path=''):
        port = port or 23
        tn = _TelnetClient()
        tn.open(host, port, timeout=10)

        # ログインプロンプト待ち（複数表現に対応）
        banner = tn.read_until(b':', timeout=10).lower()
        if b'login' in banner or b'username' in banner or b'user' in banner:
            tn.write(user.encode() + b'\r\n')
        else:
            # ヒューリスティック: 何か来たら user を送る
            tn.write(user.encode() + b'\r\n')

        if password:
            tn.read_until(b'assword:', timeout=10)
            tn.write(password.encode() + b'\r\n')

        # プロンプトが出るまで少し待つ
        time.sleep(0.5)
        tn.recv(0.5)

        self._tn = tn
        self.label = f"{user}@{host}"
        self._info = dict(host=host, port=port, user=user,
                          password=password, key_path=key_path)

    def disconnect(self):
        try:
            if self._tn:
                try:
                    self._tn.write(b'exit\r\n')
                except Exception:
                    pass
                self._tn.close()
        except Exception:
            pass
        self._tn = None

    # --- 内部: マーカー付きでコマンドを実行 ---

    def _exec_raw(self, cmd: str, timeout: float = 30) -> str:
        if not self._tn:
            return ''
        # 入力バッファに残った前回出力を捨てる
        while self._tn.recv(0.05):
            pass
        full = f'{cmd}; echo {_TELNET_END_MARKER}\r\n'
        self._tn.write(full.encode())

        out = bytearray()
        deadline = time.time() + timeout
        while time.time() < deadline:
            chunk = self._tn.recv(0.3)
            if chunk:
                out.extend(chunk)
                if _TELNET_END_MARKER.encode() in out:
                    break
        text = out.decode('utf-8', errors='replace')
        # マーカー以降を切り捨て
        idx = text.find(_TELNET_END_MARKER)
        if idx >= 0:
            text = text[:idx]
        # コマンドエコー (先頭の echo 行) を削除
        lines = text.splitlines()
        if lines and (cmd[:30] in lines[0] or _TELNET_END_MARKER in lines[0]):
            lines = lines[1:]
        # 末尾の空行・プロンプト行 (もし残っていれば) を削除
        while lines and re.search(r'[$#>]\s*$', lines[-1]):
            lines = lines[:-1]
        return '\n'.join(lines)

    def exec(self, cmd: str) -> str:
        return self._exec_raw(cmd)

    def read_tail(self, path: str, lines: int = 5000) -> str:
        return self._exec_raw(
            f'tail -n {lines} "{path}" 2>/dev/null || cat "{path}" 2>/dev/null'
        )

    def listdir(self, path: str):
        out = self._exec_raw(f'ls -la "{path}" 2>/dev/null')
        entries: list[_FakeStat] = []
        for line in out.splitlines():
            line = line.strip()
            if not line or line.startswith('total'):
                continue
            parts = line.split(None, 8)
            if len(parts) < 9:
                continue
            mode = parts[0]
            name = parts[8]
            # シンボリックリンク表記 "name -> target" は name 側だけ採用
            if ' -> ' in name:
                name = name.split(' -> ', 1)[0]
            if name in ('.', '..'):
                continue
            entries.append(_FakeStat(name, mode.startswith('d')))
        entries.sort(key=lambda a: (not stat_mod.S_ISDIR(a.st_mode), a.filename.lower()))
        return entries

    # --- ストリーミング系: 別接続を新規に開く ---

    def open_tail_channel(self, path: str) -> '_TailChannel':
        new_tn = _TelnetClient()
        new_tn.open(self._info['host'], self._info['port'], timeout=10)
        new_tn.read_until(b':', timeout=10)
        new_tn.write(self._info['user'].encode() + b'\r\n')
        if self._info.get('password'):
            new_tn.read_until(b'assword:', timeout=10)
            new_tn.write(self._info['password'].encode() + b'\r\n')
        time.sleep(0.5)
        new_tn.recv(0.5)
        # -F (= --follow=name --retry): ローテーションされても同じ名前を追従
        new_tn.write(f'tail -F "{path}"\r\n'.encode())
        return _TelnetChannel(new_tn)

    def open_shell_channel(self) -> '_TailChannel':
        new_tn = _TelnetClient()
        new_tn.open(self._info['host'], self._info['port'], timeout=10)
        new_tn.read_until(b':', timeout=10)
        new_tn.write(self._info['user'].encode() + b'\r\n')
        if self._info.get('password'):
            new_tn.read_until(b'assword:', timeout=10)
            new_tn.write(self._info['password'].encode() + b'\r\n')
        return _TelnetChannel(new_tn)

    def download_bytes(self, path: str) -> bytes:
        """リモートファイルを全文バイトで取得 (cat 経由、Base64ラップでバイナリ安全に)。"""
        # base64 を経由してバイナリでも壊れず取得
        b64 = self._exec_raw(f'base64 "{path}" 2>/dev/null', timeout=120)
        import base64 as _b64
        try:
            return _b64.b64decode(''.join(b64.split()))
        except Exception:
            # fallback: cat で文字列として取得
            return self._exec_raw(f'cat "{path}"', timeout=120).encode('utf-8', errors='replace')


# ---------------------------------------------------------------------------
# 接続クラス用の型エイリアス (Duck-typed: SSHConnection | TelnetConnection)
# ---------------------------------------------------------------------------

RemoteConnection = SSHConnection  # forward declaration; both types share API


# ---------------------------------------------------------------------------
# Tail/Shell ストリーム抽象チャネル
# ---------------------------------------------------------------------------

class _TailChannel:
    def recv_ready(self, timeout: float = 0.1) -> bool: ...
    def recv(self, n: int = 4096) -> bytes: ...
    def send(self, data: bytes): ...
    def close(self): ...


class _SSHChannel:
    def __init__(self, chan):
        self._chan = chan

    def recv_ready(self, timeout: float = 0.1) -> bool:
        # paramiko's Channel: poll then time.sleep
        if self._chan.recv_ready():
            return True
        # 短時間待つ
        t0 = time.time()
        while time.time() - t0 < timeout:
            if self._chan.recv_ready():
                return True
            time.sleep(0.02)
        return False

    def recv(self, n: int = 4096) -> bytes:
        try:
            return self._chan.recv(n)
        except Exception:
            return b''

    def send(self, data: bytes):
        # 例外は呼び出し側で見たいので飲み込まない
        self._chan.send(data)

    def close(self):
        try:
            self._chan.close()
        except Exception:
            pass


class _TelnetChannel:
    def __init__(self, tn: _TelnetClient):
        self._tn = tn
        self._buf = bytearray()

    def recv_ready(self, timeout: float = 0.1) -> bool:
        if self._buf:
            return True
        chunk = self._tn.recv(timeout)
        if chunk:
            self._buf.extend(chunk)
            return True
        return False

    def recv(self, n: int = 4096) -> bytes:
        if not self._buf:
            chunk = self._tn.recv(0.05)
            if chunk:
                self._buf.extend(chunk)
        if not self._buf:
            return b''
        data = bytes(self._buf[:n])
        del self._buf[:n]
        return data

    def send(self, data: bytes):
        # 例外は呼び出し側で見たいので飲み込まない
        self._tn.write(data)

    def close(self):
        try:
            self._tn.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Tail -f ワーカー
# ---------------------------------------------------------------------------

class TailWorker(QThread):
    new_text = pyqtSignal(str)
    error    = pyqtSignal(str)

    def __init__(self, conn, path: str):
        super().__init__()
        self._conn = conn
        self._path = path
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        chan = None
        try:
            chan = self._conn.open_tail_channel(self._path)
            buf = b''
            while not self._stop:
                if chan.recv_ready(0.1):
                    data = chan.recv(4096)
                    if not data:
                        time.sleep(0.05)
                        continue
                    buf += data
                    parts = buf.split(b'\n')
                    buf   = parts[-1]
                    text  = b'\n'.join(parts[:-1]).decode('utf-8', errors='replace')
                    if text:
                        self.new_text.emit(text)
                else:
                    time.sleep(0.05)
        except Exception as e:
            self.error.emit(str(e))
        finally:
            if chan:
                chan.close()


# ---------------------------------------------------------------------------
# ログシンタックスハイライター
# ---------------------------------------------------------------------------

_LEVEL_PATTERN = {
    'ERROR+': re.compile(r'\b(?:ERROR|CRITICAL|FATAL|SEVERE)\b', re.IGNORECASE),
    'WARN+':  re.compile(r'\b(?:WARN(?:ING)?|ERROR|CRITICAL|FATAL|SEVERE)\b', re.IGNORECASE),
    'INFO+':  re.compile(r'\b(?:INFO|WARN(?:ING)?|ERROR|CRITICAL|FATAL|SEVERE)\b', re.IGNORECASE),
}

def _filter_lines(lines: list[str], pattern: str, level: str) -> list[str]:
    lp = _LEVEL_PATTERN.get(level)
    if lp:
        lines = [l for l in lines if lp.search(l)]
    if pattern:
        try:
            pp = re.compile(pattern, re.IGNORECASE)
            lines = [l for l in lines if pp.search(l)]
        except re.error:
            pass
    return lines


class LogHighlighter(QSyntaxHighlighter):
    # レベル定義: (正規表現, テーマキー prefix)。色はテーマから引く。
    _LEVEL_PATTERNS = [
        (re.compile(r'\b(?:ERROR|CRITICAL|FATAL|SEVERE)\b', re.I), 'error'),
        (re.compile(r'\bWARN(?:ING)?\b', re.I),                    'warn'),
        (re.compile(r'\bINFO\b', re.I),                             'info'),
        (re.compile(r'\bDEBUG\b', re.I),                            'debug'),
        (re.compile(r'\bTRACE\b', re.I),                            'trace'),
    ]
    # (正規表現, テーマキー) — 色はテーマから取得
    _INLINE = [
        (re.compile(r'\d{4}[-/]\d{2}[-/]\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:\d{2})?'), 'syn_timestamp'),
        (re.compile(r'\b\d{2}:\d{2}:\d{2}(?:[.,]\d+)?\b'),      'syn_timestamp'),
        (re.compile(r'\[[\w\s.:\-/]+\]'),                        'syn_bracket'),
        (re.compile(r'\b\w+(?:Exception|Error)\b'),              'syn_exception'),
        (re.compile(r'^\s+at\s+[\w.$<>()\[\]/]+'),               'syn_stack'),
        (re.compile(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b'),  'syn_timestamp'),
        # HTTPステータスコード(4xx/5xx) ハイライトは産業ログでの誤検出が多いため無効化
    ]

    # --- SQL 検出パターン ---
    # SQL指標：これらが見つかった行のみSQLハイライトを適用 (誤検出抑止)
    _SQL_INDICATOR = re.compile(
        r'\b(?:SELECT|INSERT\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM|'
        r'CREATE\s+(?:TABLE|INDEX|VIEW|DATABASE|SCHEMA)|'
        r'ALTER\s+TABLE|DROP\s+(?:TABLE|INDEX|VIEW)|'
        r'WITH\s+\w+\s+AS|MERGE\s+INTO|TRUNCATE\s+TABLE)\b',
        re.IGNORECASE,
    )
    _SQL_KEYWORDS = re.compile(
        r'\b(?:SELECT|FROM|WHERE|AND|OR|NOT|IN|IS|NULL|LIKE|ILIKE|BETWEEN|EXISTS|'
        r'INSERT|INTO|VALUES|UPDATE|SET|DELETE|TRUNCATE|'
        r'CREATE|TABLE|INDEX|VIEW|DATABASE|SCHEMA|SEQUENCE|TRIGGER|'
        r'ALTER|DROP|ADD|COLUMN|MODIFY|RENAME|'
        r'JOIN|INNER|LEFT|RIGHT|FULL|OUTER|CROSS|ON|USING|AS|'
        r'GROUP\s+BY|ORDER\s+BY|HAVING|LIMIT|OFFSET|FETCH|DISTINCT|'
        r'UNION(?:\s+ALL)?|EXCEPT|INTERSECT|ALL|ANY|SOME|'
        r'CASE|WHEN|THEN|ELSE|END|'
        r'WITH|RECURSIVE|OVER|PARTITION\s+BY|ROW|RANGE|'
        r'BEGIN|COMMIT|ROLLBACK|TRANSACTION|SAVEPOINT|'
        r'PRIMARY\s+KEY|FOREIGN\s+KEY|REFERENCES|UNIQUE|DEFAULT|CHECK|CONSTRAINT|'
        r'IF\s+(?:NOT\s+)?EXISTS|REPLACE|MERGE|MATCHED)\b',
        re.IGNORECASE,
    )
    _SQL_TYPES = re.compile(
        r'\b(?:INT|INTEGER|BIGINT|SMALLINT|TINYINT|FLOAT|DOUBLE|DECIMAL|NUMERIC|REAL|'
        r'CHAR|VARCHAR|TEXT|NVARCHAR|NCHAR|CLOB|'
        r'DATE|TIME|DATETIME|TIMESTAMP|'
        r'BOOLEAN|BOOL|BIT|BINARY|VARBINARY|BLOB|'
        r'JSON|JSONB|XML|UUID)\b',
        re.IGNORECASE,
    )
    _SQL_FUNCTIONS = re.compile(
        r'\b(?:COUNT|SUM|AVG|MIN|MAX|COALESCE|NULLIF|IFNULL|NVL|'
        r'UPPER|LOWER|TRIM|LTRIM|RTRIM|LENGTH|LEN|SUBSTRING|SUBSTR|CONCAT|REPLACE|'
        r'NOW|GETDATE|CURRENT_DATE|CURRENT_TIME|CURRENT_TIMESTAMP|EXTRACT|DATEADD|DATEDIFF|'
        r'CAST|CONVERT|TO_CHAR|TO_DATE|TO_NUMBER|'
        r'ROW_NUMBER|RANK|DENSE_RANK|LEAD|LAG|FIRST_VALUE|LAST_VALUE|'
        r'ROUND|FLOOR|CEIL|CEILING|ABS|MOD|POWER|SQRT)\b(?=\s*\()',
        re.IGNORECASE,
    )
    _SQL_STRING = re.compile(r"'(?:[^'\\]|\\.|'')*'")
    _SQL_COMMENT = re.compile(r'--[^\n]*')
    _SQL_NUMBER = re.compile(r'\b\d+(?:\.\d+)?\b')

    # ファイル拡張子で全文SQLモード
    _SQL_FILE_EXTS = ('.sql', '.ddl', '.dml', '.pls', '.plsql')

    def __init__(self, document, mode: str = 'log'):
        super().__init__(document)
        self._mode = mode

    @classmethod
    def detect_mode_for_file(cls, filename: str) -> str:
        name = filename.lower()
        # .gz は中身の拡張子で判定
        if name.endswith('.gz'):
            name = name[:-3]
        if any(name.endswith(ext) for ext in cls._SQL_FILE_EXTS):
            return 'sql'
        return 'log'

    def set_mode(self, mode: str):
        if mode != self._mode:
            self._mode = mode
            self.rehighlight()

    def highlightBlock(self, text: str):
        if self._mode == 'sql':
            self._apply_sql(text)
            return

        # --- ログモード ---
        t = _theme()
        for pat, key in self._LEVEL_PATTERNS:
            if pat.search(text):
                fmt = QTextCharFormat()
                bg = t.get(f'level_{key}_bg')
                fg = t.get(f'level_{key}_fg')
                if bg: fmt.setBackground(QColor(bg))
                if fg: fmt.setForeground(QColor(fg))
                self.setFormat(0, len(text), fmt)
                break
        for pat, key in self._INLINE:
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(t.get(key, '#888888')))
            for m in pat.finditer(text):
                self.setFormat(m.start(), m.end() - m.start(), fmt)
        # ログ中にSQLが含まれる行のみSQL要素を上書き色分け
        if self._SQL_INDICATOR.search(text):
            self._apply_sql(text)

    def _apply_sql(self, text: str):
        t = _theme()
        # 順番: キーワード/型/関数 → 文字列 → 数値 → コメント
        kw_fmt = QTextCharFormat()
        kw_fmt.setForeground(QColor(t['syn_sql_kw']))
        kw_fmt.setFontWeight(700)
        for m in self._SQL_KEYWORDS.finditer(text):
            self.setFormat(m.start(), m.end() - m.start(), kw_fmt)

        type_fmt = QTextCharFormat()
        type_fmt.setForeground(QColor(t['syn_sql_type']))
        type_fmt.setFontWeight(700)
        for m in self._SQL_TYPES.finditer(text):
            self.setFormat(m.start(), m.end() - m.start(), type_fmt)

        fn_fmt = QTextCharFormat()
        fn_fmt.setForeground(QColor(t['syn_sql_func']))
        for m in self._SQL_FUNCTIONS.finditer(text):
            self.setFormat(m.start(), m.end() - m.start(), fn_fmt)

        num_fmt = QTextCharFormat()
        num_fmt.setForeground(QColor(t['syn_sql_num']))
        for m in self._SQL_NUMBER.finditer(text):
            self.setFormat(m.start(), m.end() - m.start(), num_fmt)

        str_fmt = QTextCharFormat()
        str_fmt.setForeground(QColor(t['syn_sql_str']))
        for m in self._SQL_STRING.finditer(text):
            self.setFormat(m.start(), m.end() - m.start(), str_fmt)

        cm_fmt = QTextCharFormat()
        cm_fmt.setForeground(QColor(t['syn_sql_cmt']))
        cm_fmt.setFontItalic(True)
        for m in self._SQL_COMMENT.finditer(text):
            self.setFormat(m.start(), m.end() - m.start(), cm_fmt)


# ---------------------------------------------------------------------------
# ミニログビューア（グリッド1セル分）
# ---------------------------------------------------------------------------

class MiniLogViewer(QWidget):
    tail_changed     = pyqtSignal(bool)
    close_requested  = pyqtSignal(object)
    editor_requested = pyqtSignal(object, str)   # conn, path
    sql_selection_requested = pyqtSignal(object, str)  # conn, 選択テキスト

    # tail 放置時のメモリ無限増加を防ぐ保持上限 (元データ・表示の両方に適用)
    _MAX_LINES = 50000

    def __init__(self, conn: SSHConnection, path: str,
                 server_label: str, color_idx: int, parent=None):
        super().__init__(parent)
        self.conn         = conn
        self.filepath     = path
        self.server_label = server_label
        self.color_idx    = color_idx
        self._all_lines: list[str] = []
        self._worker: TailWorker | None = None
        self._bg, self._fg = _palette(color_idx)
        self._build_ui()
        self._load()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── ヘッダー（サーバー色） ────────────────────────────────────
        header = QWidget()
        header.setFixedHeight(30)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(5, 0, 2, 0)
        hl.setSpacing(4)

        self._header = header
        self._header_dot = QLabel("●")
        self._header_dot.setFixedWidth(10)
        hl.addWidget(self._header_dot)

        self._header_lbl = QLabel(
            f"{self.server_label}  ·  {os.path.basename(self.filepath)}"
        )
        # フルパス + 接続情報を tooltip で確認可能に
        self._header_lbl.setToolTip(
            f"接続: {self.conn.label}\nパス: {self.filepath}"
        )
        hl.addWidget(self._header_lbl, 1)

        self._header_btns: list[QPushButton] = []
        # role: 'tail' = トグル / 'stop' = 停止専用 / 他は通常クリック
        for text, tip, slot, role in [
            ("▶", "Tail -F 開始 (リアルタイム追従 / ログローテーション自動追従)", None, 'tail'),
            ("■", "Tail 停止 (このセルのみ)", None, 'stop'),
            ("↺", "再読み込み", self._load, None),
            ("📝", "Sora Editor で開く (Ctrl+E で次のエラー行へジャンプ可能)",
                  lambda: self.editor_requested.emit(self.conn, self.filepath), None),
            ("✕", "閉じる", lambda: self.close_requested.emit(self), None),
        ]:
            btn = QPushButton(text)
            btn.setFixedSize(30, 26)
            btn.setToolTip(tip)
            if role == 'tail':
                btn.setCheckable(True)
                self.tail_btn = btn
                btn.toggled.connect(self._toggle_tail)
            elif role == 'stop':
                self.stop_btn = btn
                btn.setEnabled(False)           # 起動直後は無効
                btn.clicked.connect(self.stop_tail)
            else:
                btn.clicked.connect(slot)
            hl.addWidget(btn)
            self._header_btns.append(btn)
        root.addWidget(header)

        # ── フィルタバー（超コンパクト） ─────────────────────────────
        self._fbar = QWidget()
        self._fbar.setFixedHeight(20)
        fl = QHBoxLayout(self._fbar)
        fl.setContentsMargins(4, 1, 4, 1)
        fl.setSpacing(3)

        self.filter_input = QLineEdit()
        self.filter_input.setPlaceholderText("フィルタ...")
        self.filter_input.setToolTip(
            "このセルだけのフィルタ — 検索文字列または正規表現 (即時反映)"
        )
        self.filter_input.textChanged.connect(self._apply_filter)
        fl.addWidget(self.filter_input, 1)

        self.level_combo = QComboBox()
        self.level_combo.addItems(["ALL", "ERR+", "WRN+", "INF+"])
        self.level_combo.setFixedWidth(52)
        self.level_combo.setToolTip(
            "このセルだけのレベルフィルタ:\n"
            "  ALL  = 全行\n"
            "  ERR+ = ERROR/CRITICAL/FATAL のみ\n"
            "  WRN+ = WARN以上\n"
            "  INF+ = INFO以上"
        )
        self.level_combo.currentIndexChanged.connect(self._apply_filter)
        fl.addWidget(self.level_combo)
        root.addWidget(self._fbar)

        # ── テキストエリア ────────────────────────────────────────────
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        # 行数上限を設定し、古い行を自動破棄してメモリ無限増加を防ぐ
        self.text.setMaximumBlockCount(self._MAX_LINES)
        mode = LogHighlighter.detect_mode_for_file(self.filepath)
        self.highlighter = LogHighlighter(self.text.document(), mode=mode)
        # 右クリックで「選択範囲をSoraでSQL抽出」を出すためカスタムメニュー
        self.text.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.text.customContextMenuRequested.connect(self._on_text_context_menu)
        root.addWidget(self.text, 1)

        # ── ステータス（超コンパクト） ────────────────────────────────
        self.stats = QLabel("")
        self.stats.setFixedHeight(14)
        root.addWidget(self.stats)

        self.apply_settings()

    def apply_settings(self):
        fs = SETTINGS.get('log_font_size', 9)
        t = _theme()
        # サーバー識別色をテーマに応じて再取得
        self._bg, self._fg = _palette(self.color_idx)
        self._header.setStyleSheet(f"background:{self._bg};")
        self._header_dot.setStyleSheet(f"color:{self._fg}; font-size:9px;")
        self._header_lbl.setStyleSheet(
            f"color:{self._fg}; font-size:10px; font-weight:600;"
        )
        # ヘッダー上のミニボタンのスタイルもテーマに合わせる
        is_light = SETTINGS.get('theme', 'Dark') in ('Light', 'Solarized Light')
        if is_light:
            mini_btn_style = (
                f"QPushButton{{background:#ffffff80;color:{self._fg};border:none;"
                f"font-size:13px;font-weight:bold;}}"
                f"QPushButton:hover{{background:#ffffffc0;}}"
                f"QPushButton:checked{{background:{t['selection']};color:{t['text']};}}"
            )
        else:
            mini_btn_style = (
                "QPushButton{background:#00000060;color:#ffffff;border:none;"
                "font-size:13px;font-weight:bold;}"
                "QPushButton:hover{background:#000000a0;}"
                f"QPushButton:checked{{background:{t['selection']};}}"
            )
        for btn in self._header_btns:
            btn.setStyleSheet(mini_btn_style)

        self.text.setFont(QFont("Consolas", fs))
        self.text.setStyleSheet(
            f"background:{t['log_bg']};color:{t['text']};border:none;"
            f"selection-background-color:{t['selection']};"
        )
        self._fbar.setStyleSheet(f"background:{t['toolbar_bg']};")
        self.filter_input.setStyleSheet(
            f"background:{t['panel_bg']};color:{t['text']};"
            f"border:1px solid {t['border']};padding:0 2px;font-size:10px;"
        )
        self.level_combo.setStyleSheet(
            f"background:{t['panel_bg']};color:{t['text']};"
            f"border:1px solid {t['border']};font-size:10px;"
            "QComboBox::drop-down{border:none;width:12px;}"
        )
        self.stats.setStyleSheet(
            f"background:{t['toolbar_bg']};color:{t['text_dim']};"
            f"padding:0 4px;font-size:9px;"
        )
        # レベル色など Theme 連動のハイライトを再適用
        try:
            self.highlighter.rehighlight()
        except Exception:
            pass

    def _on_text_context_menu(self, pos):
        """ログ本文の右クリックメニュー (コピー + 選択範囲SQL抽出)。"""
        from PyQt6.QtWidgets import QMenu
        menu = QMenu(self.text)
        has_sel = self.text.textCursor().hasSelection()

        a_copy = menu.addAction("コピー")
        a_copy.setEnabled(has_sel)
        a_copy.triggered.connect(self.text.copy)

        a_all = menu.addAction("すべて選択")
        a_all.triggered.connect(self.text.selectAll)

        menu.addSeparator()

        a_sql = menu.addAction("選択範囲をSoraでSQL抽出・実行...")
        a_sql.setEnabled(has_sel)
        if not has_sel:
            a_sql.setToolTip("先にSQLを含むログ範囲を選択してください")
        a_sql.triggered.connect(
            lambda: self.sql_selection_requested.emit(
                self.conn, self.text.textCursor().selection().toPlainText()
            )
        )

        menu.exec(self.text.mapToGlobal(pos))

    # ── データ操作 ─────────────────────────────────────────────────────

    def _load(self):
        self.stats.setText("読込中...")
        try:
            content = self.conn.read_tail(self.filepath)
            self._all_lines = content.splitlines()
            self._apply_filter()
        except Exception as e:
            self.stats.setText(f"ERR: {e}")

    def _level_key(self) -> str:
        return {'ERR+': 'ERROR+', 'WRN+': 'WARN+', 'INF+': 'INFO+', 'ALL': 'ALL'}.get(
            self.level_combo.currentText(), 'ALL'
        )

    def _apply_filter(self):
        lines = _filter_lines(self._all_lines, self.filter_input.text(), self._level_key())
        self.text.setPlainText('\n'.join(lines))
        ec = sum(1 for l in lines if re.search(r'\b(?:ERROR|CRITICAL|FATAL)\b', l, re.I))
        wc = sum(1 for l in lines if re.search(r'\bWARN', l, re.I))
        self.stats.setText(f"ERR:{ec}  WRN:{wc}  行:{len(lines)}")

    def _toggle_tail(self, on: bool):
        if on:
            self._worker = TailWorker(self.conn, self.filepath)
            self._worker.new_text.connect(self._append)
            self._worker.error.connect(lambda e: self.stats.setText(f"ERR:{e}"))
            self._worker.start()
        else:
            self._stop_worker()
        if hasattr(self, 'stop_btn'):
            self.stop_btn.setEnabled(on)
        self.tail_changed.emit(on)

    def _append(self, text: str):
        self._all_lines.extend(text.splitlines())
        # 元データも上限で丸めてメモリ無限増加を防ぐ (表示は maximumBlockCount で別途制限)
        if len(self._all_lines) > self._MAX_LINES:
            del self._all_lines[:len(self._all_lines) - self._MAX_LINES]
        if not self.filter_input.text() and self._level_key() == 'ALL':
            self.text.appendPlainText(text)
        else:
            self._apply_filter()
        sb = self.text.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _stop_worker(self):
        if self._worker:
            self._worker.stop()
            self._worker.wait()
            self._worker = None

    # ── 外部 API ──────────────────────────────────────────────────────

    def start_tail(self):
        self.tail_btn.setChecked(True)

    def stop_tail(self):
        self.tail_btn.setChecked(False)
        self._stop_worker()

    def set_filter(self, pattern: str, level: str):
        lvl_map = {'ALL': 'ALL', 'ERROR+': 'ERR+', 'WARN+': 'WRN+', 'INFO+': 'INF+'}
        self.filter_input.setText(pattern)
        t = lvl_map.get(level, 'ALL')
        i = self.level_combo.findText(t)
        if i >= 0:
            self.level_combo.setCurrentIndex(i)


# ---------------------------------------------------------------------------
# 空きセルプレースホルダー
# ---------------------------------------------------------------------------

class EmptyCell(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._label = QLabel("空き\nファイルをダブルクリックで開く")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay = QVBoxLayout(self)
        lay.addWidget(self._label)
        self.apply_settings()

    def apply_settings(self):
        t = _theme()
        self.setStyleSheet(
            f"background:{t['log_bg']}; border:1px solid {t['border']};"
        )
        self._label.setStyleSheet(
            f"color:{t['text_dim']}; font-size:11px; border:none;"
        )


# ---------------------------------------------------------------------------
# セルスロット（EmptyCell / MiniLogViewer を切り替え可能なコンテナ）
# ---------------------------------------------------------------------------

class CellSlot(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._lay  = QVBoxLayout(self)
        self._lay.setContentsMargins(1, 1, 1, 1)
        self._lay.setSpacing(0)
        self._child: QWidget = EmptyCell()
        self._lay.addWidget(self._child)

    def assign(self, viewer: MiniLogViewer):
        self._remove_current()
        self._child = viewer
        self._lay.addWidget(viewer)
        viewer.show()
        viewer.close_requested.connect(self._on_close)

    def _on_close(self, _):
        self.clear()

    def clear(self):
        self._remove_current()
        self._child = EmptyCell()
        self._lay.addWidget(self._child)

    def _remove_current(self):
        if isinstance(self._child, MiniLogViewer):
            self._child.stop_tail()
        self._lay.removeWidget(self._child)
        self._child.deleteLater()

    def is_empty(self) -> bool:
        return isinstance(self._child, EmptyCell)

    def viewer(self) -> MiniLogViewer | None:
        return self._child if isinstance(self._child, MiniLogViewer) else None


# ---------------------------------------------------------------------------
# ロググリッド（N×M の CellSlot を入れ子スプリッターで管理）
# ---------------------------------------------------------------------------

class LogGrid(QWidget):
    def __init__(self, rows: int = 2, cols: int = 2, parent=None):
        super().__init__(parent)
        self._rows  = rows
        self._cols  = cols
        self._slots: list[CellSlot] = []
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(0, 0, 0, 0)
        self._hsplit: QSplitter | None = None
        self._rebuild()

    def _rebuild(self):
        n = self._rows * self._cols
        # スロット数を調整（減る場合はスロットを閉じる）
        while len(self._slots) < n:
            self._slots.append(CellSlot())
        for extra in self._slots[n:]:
            v = extra.viewer()
            if v: v.stop_tail()
            extra.setParent(None)
            extra.deleteLater()
        self._slots = self._slots[:n]

        # 既存スプリッターを除去 (kept slots は先に親解除して退避)
        if self._hsplit:
            for slot in self._slots:
                slot.setParent(None)
            self._outer.removeWidget(self._hsplit)
            self._hsplit.deleteLater()
            self._hsplit = None

        # ネストされた QSplitter を構築
        hsplit = QSplitter(Qt.Orientation.Horizontal)
        hsplit.setHandleWidth(2)
        self._vsplits: list[QSplitter] = []
        for col in range(self._cols):
            vsplit = QSplitter(Qt.Orientation.Vertical)
            vsplit.setHandleWidth(2)
            for row in range(self._rows):
                slot = self._slots[row * self._cols + col]
                vsplit.addWidget(slot)
                slot.show()  # setParent(None) で隠れていた場合に備え明示表示
                v = slot.viewer()
                if v:
                    v.show()
                vsplit.setStretchFactor(row, 1)
            hsplit.addWidget(vsplit)
            hsplit.setStretchFactor(col, 1)
            self._vsplits.append(vsplit)

        self._hsplit = hsplit
        self._outer.addWidget(hsplit)
        hsplit.show()

        # レイアウト確定後に均等分割を適用 (幅が確定するまで少し待つ)
        QTimer.singleShot(30, self._equalize)

    def _equalize(self):
        """全スプリッターを均等分割する。幅が未確定なら no-op (stretch factor に委ねる)。"""
        if not self._hsplit:
            return
        w = self._hsplit.width()
        h = self._hsplit.height()
        # 幅未確定の場合は setSizes(0) を避け、再試行
        if w < 50 or h < 50:
            QTimer.singleShot(50, self._equalize)
            return
        if self._cols > 0:
            self._hsplit.setSizes([w // self._cols] * self._cols)
        for vsplit in self._vsplits:
            if self._rows > 0:
                vsplit.setSizes([h // self._rows] * self._rows)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # リサイズ後も均等を維持（ユーザーが手動調整した場合は上書きしない）
        # 初期表示のみ均等化するため、ここでは何もしない
        pass

    def set_size(self, rows: int, cols: int):
        self._rows = rows
        self._cols = cols
        self._rebuild()

    def assign(self, viewer: MiniLogViewer) -> bool:
        for slot in self._slots:
            if slot.is_empty():
                slot.assign(viewer)
                return True
        return False

    def viewers(self) -> list[MiniLogViewer]:
        return [s.viewer() for s in self._slots if s.viewer()]

    def start_all_tail(self):
        for v in self.viewers(): v.start_tail()

    def stop_all_tail(self):
        for v in self.viewers(): v.stop_tail()

    def apply_filter(self, pattern: str, level: str):
        for v in self.viewers(): v.set_filter(pattern, level)

    def apply_settings(self):
        """テーマ変更時に空セル/ビューア両方を更新"""
        for slot in self._slots:
            child = slot._child
            if isinstance(child, EmptyCell):
                child.apply_settings()
            elif isinstance(child, MiniLogViewer):
                child.apply_settings()


# ---------------------------------------------------------------------------
# リモートファイルブラウザ（1サーバー分）
# ---------------------------------------------------------------------------

class ServerPanel(QWidget):
    """1サーバーの接続状態＋ファイルツリー"""
    file_open_requested    = pyqtSignal(object, str, int)   # conn, path, color_idx
    edit_open_requested    = pyqtSignal(object, str)        # conn, path
    disconnect_requested   = pyqtSignal(object)             # self
    save_dir_requested     = pyqtSignal(object, str)        # self, path
    terminal_requested     = pyqtSignal(object)             # self

    def __init__(self, conn: SSHConnection, color_idx: int,
                 initial_path: str = '/var/log', parent=None):
        super().__init__(parent)
        self.conn         = conn
        self.color_idx    = color_idx
        self._initial_path = initial_path.strip() or '/var/log'
        self._bg, self._fg = _palette(color_idx)
        self._build_ui()
        self._load(self._initial_path)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(1)

        # サーバーヘッダー (apply_settings で配色を都度更新)
        self._header = QWidget()
        self._header.setFixedHeight(24)
        hl = QHBoxLayout(self._header)
        hl.setContentsMargins(6, 0, 4, 0)
        hl.setSpacing(4)
        self._header_dot = QLabel("●")
        hl.addWidget(self._header_dot)
        self._header_lbl = QLabel(self._make_header_text())
        self._header_lbl.setToolTip(self.conn.label)   # フル user@host はツールチップで
        hl.addWidget(self._header_lbl, 1)

        self._term_btn = QPushButton("⌨ ターミナル")
        self._term_btn.setFixedHeight(18)
        self._term_btn.setToolTip("ターミナルを開く")
        self._term_btn.clicked.connect(lambda: self.terminal_requested.emit(self))
        hl.addWidget(self._term_btn)

        self._disc_btn = QPushButton("切断")
        self._disc_btn.setFixedHeight(18)
        self._disc_btn.clicked.connect(lambda: self.disconnect_requested.emit(self))
        hl.addWidget(self._disc_btn)
        layout.addWidget(self._header)

        # パスバーラベル
        self._path_hint = QLabel("📁 表示中のフォルダ:")
        self._path_hint.setStyleSheet("color:#888; font-size:10px; padding:2px 4px 0 4px;")
        layout.addWidget(self._path_hint)

        path_row = QHBoxLayout()
        path_row.setContentsMargins(2, 1, 2, 1)
        path_row.setSpacing(2)
        _pt = _theme()
        _pbtn = (f"background:{_pt['control_bg']};color:{_pt['text']};"
                 f"border:1px solid {_pt['border']};border-radius:3px;font-weight:bold;")
        up_btn = QPushButton("⬆")
        up_btn.setFixedSize(20, 18)
        up_btn.setToolTip("親フォルダへ移動")
        up_btn.setStyleSheet(_pbtn)
        up_btn.clicked.connect(self._go_parent)
        self.path_input = QLineEdit(self._initial_path)
        self.path_input.setToolTip("リモートサーバーのフォルダパスを入力して Enter または → で移動")
        self.path_input.returnPressed.connect(lambda: self._load(self.path_input.text()))
        go_btn = QPushButton("→")
        go_btn.setFixedSize(20, 18)
        go_btn.setToolTip("入力したフォルダに移動")
        go_btn.setStyleSheet(_pbtn)
        go_btn.clicked.connect(lambda: self._load(self.path_input.text()))
        refresh_btn = QPushButton("↻")
        refresh_btn.setFixedSize(22, 18)
        refresh_btn.setToolTip(
            "現在のフォルダを再読み込み (ローテーションされた新ファイルを表示)"
        )
        refresh_btn.setStyleSheet(_pbtn + "font-size:13px;")
        refresh_btn.clicked.connect(lambda: self._load(self.path_input.text()))
        save_btn = QPushButton("📌")
        save_btn.setFixedSize(22, 18)
        save_btn.setToolTip("現在のフォルダを「次回接続時の初期DIR」としてプロファイルに保存")
        save_btn.setStyleSheet(_pbtn + "font-size:11px;")
        save_btn.clicked.connect(
            lambda: self.save_dir_requested.emit(self, self.path_input.text())
        )
        path_row.addWidget(up_btn)
        path_row.addWidget(self.path_input, 1)
        path_row.addWidget(go_btn)
        path_row.addWidget(refresh_btn)
        path_row.addWidget(save_btn)
        layout.addLayout(path_row)

        # クイックアクセス — コンテナにまとめて一括表示/非表示可能に
        self._quick_container = QWidget()
        quick_vl = QVBoxLayout(self._quick_container)
        quick_vl.setContentsMargins(0, 0, 0, 0)
        quick_vl.setSpacing(0)

        self._quick_hint = QLabel("⚡ クイックジャンプ:")
        self._quick_hint.setStyleSheet("color:#888; font-size:10px; padding:4px 4px 0 4px;")
        quick_vl.addWidget(self._quick_hint)

        quick = QHBoxLayout()
        quick.setContentsMargins(2, 0, 2, 0)
        quick.setSpacing(2)
        self._quick_btns: list[QPushButton] = []
        quick_items = [
            ("📋 ログ",   "/var/log", "/var/log — Linux標準のシステム・アプリログ保管DIR"),
            ("🏠 ホーム", "~",        "~ — ログインユーザーのホームDIR"),
            ("🗂 /tmp",  "/tmp",     "/tmp — 一時ファイル領域"),
        ]
        for label, path, tip in quick_items:
            btn = QPushButton(label)
            btn.setFixedHeight(18)
            btn.setToolTip(tip)
            btn.clicked.connect(lambda _, p=path: self._load(p))
            quick.addWidget(btn)
            self._quick_btns.append(btn)
        quick.addStretch()
        quick_vl.addLayout(quick)
        layout.addWidget(self._quick_container)

        # ファイルツリーラベル
        self._tree_hint = QLabel("📄 ダブルクリックでログを開く:")
        self._tree_hint.setStyleSheet("color:#888; font-size:10px; padding:4px 4px 0 4px;")
        layout.addWidget(self._tree_hint)

        # ファイルツリー
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.itemDoubleClicked.connect(self._on_double_click)
        self.tree.itemExpanded.connect(self._on_expand)
        # フォルダをクリックしたらパス欄に反映 (📌保存の対象DIRと一致させる)
        self.tree.itemClicked.connect(self._on_tree_clicked)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_tree_context_menu)
        layout.addWidget(self.tree, 1)

        self.apply_settings()

    def _make_header_text(self) -> str:
        """ヘッダー表示テキスト: プロファイル名があれば優先、なければ user@host"""
        proto_tag = getattr(self.conn, 'protocol', 'ssh').upper()
        name = getattr(self, '_profile_name', None)
        if name and name != '-- 新規 --':
            return f"[{proto_tag}] {name}"
        return f"[{proto_tag}] {self.conn.label}"

    def refresh_header_label(self):
        """プロファイル名設定後に呼んでヘッダーラベルを更新"""
        self._header_lbl.setText(self._make_header_text())
        self._header_lbl.setToolTip(self.conn.label)

    def apply_settings(self):
        fs = SETTINGS.get('tree_font_size', 10)
        t = _theme()
        # サーバー識別色をテーマに応じて取り直し、ヘッダーを再着色
        self._bg, self._fg = _palette(self.color_idx)
        self._header.setStyleSheet(f"background:{self._bg};")
        self._header_dot.setStyleSheet(f"color:{self._fg}; font-size:10px;")
        self._header_lbl.setStyleSheet(
            f"color:{self._fg}; font-size:11px; font-weight:600;"
        )
        # ヘッダー上のボタン: 暗ヘッダーなら白文字、明ヘッダーなら濃色文字
        is_light = SETTINGS.get('theme', 'Dark') in ('Light', 'Solarized Light')
        if is_light:
            hdr_btn_style = (
                f"QPushButton{{background:#ffffff80;color:{self._fg};border:none;"
                f"padding:0 8px;font-size:11px;font-weight:600;}}"
                f"QPushButton:hover{{background:#ffffffc0;}}"
            )
        else:
            hdr_btn_style = (
                "QPushButton{background:#00000060;color:#ffffff;border:none;"
                "padding:0 8px;font-size:11px;font-weight:600;}"
                "QPushButton:hover{background:#000000a0;}"
            )
        self._term_btn.setStyleSheet(hdr_btn_style)
        self._disc_btn.setStyleSheet(hdr_btn_style)

        # サイドバー本体
        self.path_input.setStyleSheet(
            f"background:{t['panel_bg']};color:{t['text']};"
            f"border:1px solid {t['border']};"
            f"padding:1px 3px;font-size:{fs}px;"
        )
        for btn in self._quick_btns:
            btn.setStyleSheet(
                f"background:{t['control_bg']};color:{t['text_dim']};border:none;"
                f"padding:0 3px;font-size:{max(fs-1, 7)}px;"
            )
        self.tree.setStyleSheet(
            f"QTreeWidget{{background:{t['panel_bg']};color:{t['text']};border:none;font-size:{fs}px;}}"
            f"QTreeWidget::item{{padding:1px 0;}}"
            f"QTreeWidget::item:selected{{background:{t['selection']};color:{t['text']};}}"
            f"QTreeWidget::item:hover{{background:{t['control_bg']};}}"
        )
        # 表示/非表示の切り替え (画面の縦スペースを節約)
        self._quick_container.setVisible(SETTINGS.get('show_quick_jump', True))
        show_hints = SETTINGS.get('show_panel_hints', True)
        self._path_hint.setVisible(show_hints)
        self._quick_hint.setVisible(show_hints)
        self._tree_hint.setVisible(show_hints)

    def _go_parent(self):
        """現在表示中のフォルダの親フォルダへ移動する。"""
        cur = self.path_input.text().strip() or '/'
        # 末尾スラッシュを除去してから親を求める
        cur = cur.rstrip('/')
        if not cur or cur == '':
            parent = '/'
        else:
            parent = cur.rsplit('/', 1)[0]
            if parent == '':
                parent = '/'   # ルート直下 (/foo) の親は /
        self._load(parent)

    def _load(self, path: str):
        if path.strip() == '~':
            path = self.conn.exec('echo $HOME').strip()
        self.path_input.setText(path)
        self.tree.clear()
        self._fill(self.tree.invisibleRootItem(), path)
        # 接続時の初期DIRは設定済みの log_dir (📌で保存する初期値) を使う方針のため、
        # ここでナビゲート先を自動保存することはしない (前回DIRの自動復元は廃止)。

    def _fill(self, parent, path: str):
        try:
            for entry in self.conn.listdir(path):
                is_dir = stat_mod.S_ISDIR(entry.st_mode)
                name   = entry.filename
                full   = path.rstrip('/') + '/' + name
                item   = QTreeWidgetItem()
                item.setText(0, ("▸ " if is_dir else "  ") + name)
                item.setData(0, Qt.ItemDataRole.UserRole, {'path': full, 'is_dir': is_dir})
                if not is_dir and any(name.endswith(x) for x in ('.log', '.out', '.err', '.gz')):
                    item.setForeground(0, QColor(self._fg))
                if is_dir:
                    QTreeWidgetItem(item).setText(0, '...')
                parent.addChild(item)
        except Exception as e:
            err = QTreeWidgetItem()
            err.setText(0, f'⚠ {e}')
            err.setForeground(0, QColor('#FF7070'))
            parent.addChild(err)

    def _on_expand(self, item):
        d = item.data(0, Qt.ItemDataRole.UserRole)
        if d and d['is_dir'] and item.childCount() == 1 and item.child(0).text(0) == '...':
            item.takeChildren()
            self._fill(item, d['path'])

    def _on_tree_clicked(self, item, _col):
        """フォルダをクリックしたら、そのパスを path 欄に反映する。
        これで「📌 でそのフォルダを初期DIRに保存」が正しく効く。"""
        d = item.data(0, Qt.ItemDataRole.UserRole)
        if d and d.get('is_dir'):
            self.path_input.setText(d['path'])

    def _on_double_click(self, item, _col):
        d = item.data(0, Qt.ItemDataRole.UserRole)
        if d and not d['is_dir']:
            self.file_open_requested.emit(self.conn, d['path'], self.color_idx)

    def _on_tree_context_menu(self, pos):
        """ツリーの右クリックメニュー (ファイルのみ)。"""
        from PyQt6.QtWidgets import QMenu
        item = self.tree.itemAt(pos)
        if not item:
            return
        d = item.data(0, Qt.ItemDataRole.UserRole)
        if not d or d.get('is_dir'):
            return  # フォルダにはメニューを出さない

        menu = QMenu(self)
        _mt = _theme()
        menu.setStyleSheet(
            f"QMenu{{background:{_mt['panel_bg']};color:{_mt['text']};border:1px solid {_mt['border']};}}"
            f"QMenu::item{{padding:6px 18px;}}"
            f"QMenu::item:selected{{background:{_mt['selection']};}}"
            f"QMenu::separator{{height:1px;background:{_mt['border']};margin:4px 8px;}}"
        )

        act_log = menu.addAction("📊 ログビューアで開く (グリッドに追加)")
        menu.addSeparator()
        act_edit = menu.addAction("📝 テキストエディタで開く (ダウンロード)")

        chosen = menu.exec(self.tree.viewport().mapToGlobal(pos))
        if chosen == act_log:
            self.file_open_requested.emit(self.conn, d['path'], self.color_idx)
        elif chosen == act_edit:
            self.edit_open_requested.emit(self.conn, d['path'])


# ---------------------------------------------------------------------------
# SSH接続ダイアログ
# ---------------------------------------------------------------------------

class SSHConnectDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("サーバー接続")
        self.setMinimumWidth(380)
        self._profiles = _load_profiles()
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(5)

        pr = QHBoxLayout()
        pr.addWidget(QLabel("プロファイル:"))
        self.combo = QComboBox()
        self.combo.addItem("-- 新規 --")
        for n in self._profiles:
            self.combo.addItem(n)
        self.combo.currentIndexChanged.connect(self._on_select)
        pr.addWidget(self.combo, 1)
        for text, slot, width in [("保存", self._save, 40), ("管理", self._manage, 40)]:
            btn = QPushButton(text)
            btn.setFixedWidth(width)
            btn.clicked.connect(slot)
            pr.addWidget(btn)
        lay.addLayout(pr)

        # プロトコル選択
        proto_row = QHBoxLayout()
        proto_row.addWidget(QLabel("プロトコル:"))
        self.proto_combo = QComboBox()
        self.proto_combo.addItems(["SSH", "Telnet"])
        self.proto_combo.setFixedWidth(90)
        self.proto_combo.currentTextChanged.connect(self._on_proto_change)
        proto_row.addWidget(self.proto_combo)
        proto_row.addStretch()
        lay.addLayout(proto_row)

        g = QGridLayout()
        g.setSpacing(4)
        fields = [
            ("ホスト:",      "host",     "接続先 (IP または FQDN)",  False),
            ("ホスト名:",    "hostname", "アラートメール照合用 (例: cts7031)", False),
            ("ポート:",      "port",     "22",                    False),
            ("ユーザー:",    "user",     "",                      False),
            ("パスワード:",  "password", "",                      True),
            ("秘密鍵:",     "key_path", "~/.ssh/id_rsa (省略可)", False),
            ("ログDIR:",    "log_dir",  "/var/log",               False),
        ]
        self._fields: dict[str, QLineEdit] = {}
        self._field_rows: dict[str, list] = {}  # ラベル + 入力 widget の参照
        for r, (label, key, ph, pw) in enumerate(fields):
            lbl = QLabel(label)
            g.addWidget(lbl, r, 0)
            le = QLineEdit()
            le.setPlaceholderText(ph)
            if pw: le.setEchoMode(QLineEdit.EchoMode.Password)
            if key == 'port': le.setText("22")
            self._fields[key] = le
            if key == 'key_path':
                row = QHBoxLayout()
                row.addWidget(le)
                btn = QPushButton("...")
                btn.setFixedWidth(24)
                btn.clicked.connect(self._browse_key)
                row.addWidget(btn)
                g.addLayout(row, r, 1)
                self._field_rows[key] = [lbl, le, btn]
            else:
                g.addWidget(le, r, 1)
                self._field_rows[key] = [lbl, le]
        lay.addLayout(g)

        btns = QHBoxLayout()
        ok = QPushButton("接続")
        ok.setProperty("primary", True)   # 主アクション → 緑で強調
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        cancel = QPushButton("キャンセル")
        cancel.clicked.connect(self.reject)
        btns.addWidget(ok)
        btns.addWidget(cancel)
        lay.addLayout(btns)

        t = _theme()
        self.setStyleSheet(f"""
            QDialog{{background:{t['bg']};}}
            QLabel{{color:{t['text']};}}
            QLineEdit{{background:{t['panel_bg']};color:{t['text']};border:1px solid {t['border']};padding:1px 3px;}}
            QPushButton{{background:{t['control_bg']};color:{t['text']};border:none;padding:2px 8px;border-radius:2px;}}
            QPushButton:hover{{background:{t['control_hover']};}}
            QPushButton[primary='true']{{background:#3a6e3a;color:#e0f0e0;border:1px solid #4a8e4a;font-weight:600;padding:3px 14px;}}
            QPushButton[primary='true']:hover{{background:#4a8e4a;border:1px solid #5aa05a;}}
            QComboBox{{background:{t['control_bg']};color:{t['text']};border:1px solid {t['border']};padding:1px 3px;}}
            QComboBox::drop-down{{border:none;width:14px;}}
            QComboBox QAbstractItemView{{background:{t['panel_bg']};color:{t['text']};selection-background-color:{t['selection']};}}
        """)

    def _on_select(self, idx):
        if idx == 0: return
        p = self._profiles.get(self.combo.currentText(), {})
        for k, le in self._fields.items():
            le.setText(str(p.get(k, '')))
        proto = p.get('protocol', 'SSH')
        i = self.proto_combo.findText(proto)
        if i >= 0:
            self.proto_combo.setCurrentIndex(i)

    def _on_proto_change(self, text: str):
        is_telnet = (text == 'Telnet')
        # デフォルトポート切替（ユーザーが触っていれば尊重）
        cur_port = self._fields['port'].text().strip()
        if cur_port in ('', '22', '23'):
            self._fields['port'].setText('23' if is_telnet else '22')
        # Telnet では秘密鍵欄を無効化
        for w in self._field_rows.get('key_path', []):
            w.setEnabled(not is_telnet)

    def _save(self):
        current = self.combo.currentText()
        default_name = '' if current == '-- 新規 --' else current
        name, ok = QInputDialog.getText(
            self, "保存", "プロファイル名:", text=default_name
        )
        if not ok or not name.strip(): return
        name = name.strip()
        if name in self._profiles and name != default_name:
            ans = QMessageBox.question(
                self, "上書き確認",
                f"「{name}」は既に存在します。上書きしますか？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if ans != QMessageBox.StandardButton.Yes:
                return
        self._profiles[name] = self._info()
        _save_profiles(self._profiles)
        if self.combo.findText(name) < 0:
            self.combo.addItem(name)
        self.combo.setCurrentText(name)

    def _manage(self):
        """プロファイル管理ダイアログ (並べ替え/名前変更/削除) を開く"""
        cur = self.combo.currentText()
        dlg = ProfileManagerDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            # ファイルから再読込してコンボに反映
            self._profiles = _load_profiles()
            self.combo.blockSignals(True)
            self.combo.clear()
            self.combo.addItem("-- 新規 --")
            for n in self._profiles:
                self.combo.addItem(n)
            # 元の選択を復元 (削除/改名されていなければ)
            idx = self.combo.findText(cur)
            self.combo.setCurrentIndex(idx if idx >= 0 else 0)
            self.combo.blockSignals(False)

    def _browse_key(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "秘密鍵", os.path.expanduser("~/.ssh")
        )
        if path: self._fields['key_path'].setText(path)

    def _info(self) -> dict:
        d = {k: le.text() for k, le in self._fields.items()}
        d['protocol'] = self.proto_combo.currentText()
        return d

    def get_info(self) -> dict:
        info = self._info()
        proto = info.get('protocol', 'SSH')
        default_port = 23 if proto == 'Telnet' else 22
        info['port'] = int(info.get('port') or default_port)
        return info


# ---------------------------------------------------------------------------
# 設定ダイアログ
# ---------------------------------------------------------------------------

class ProfileManagerDialog(QDialog):
    """サーバー接続プロファイルの並べ替え/名前変更/削除を行うダイアログ"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("接続プロファイル管理")
        self.setMinimumSize(420, 360)
        self._profiles = _load_profiles()
        self._build_ui()
        self._populate()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        hint = QLabel("ドラッグで並べ替え / ダブルクリックで名前変更")
        hint.setStyleSheet("color:#888;font-size:10px;")
        lay.addWidget(hint)

        self.list = QListWidget()
        self.list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.list.itemDoubleClicked.connect(self._on_rename)
        lay.addWidget(self.list, 1)

        ops = QHBoxLayout()
        rename_btn = QPushButton("✏ 名前変更")
        rename_btn.clicked.connect(self._on_rename_selected)
        delete_btn = QPushButton("🗑 削除")
        delete_btn.clicked.connect(self._on_delete)
        ops.addWidget(rename_btn)
        ops.addWidget(delete_btn)
        ops.addStretch()
        lay.addLayout(ops)

        btns = QHBoxLayout()
        btns.addStretch()
        ok = QPushButton("OK")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        cancel = QPushButton("キャンセル")
        cancel.clicked.connect(self.reject)
        btns.addWidget(ok)
        btns.addWidget(cancel)
        lay.addLayout(btns)

        t = _theme()
        self.setStyleSheet(f"""
            QDialog {{ background:{t['bg']}; }}
            QLabel  {{ color:{t['text']}; }}
            QListWidget {{ background:{t['panel_bg']}; color:{t['text']};
                          border:1px solid {t['border']}; font-size:12px; }}
            QListWidget::item {{ padding:4px 6px; }}
            QListWidget::item:selected {{ background:{t['selection']}; color:{t['text']}; }}
            QPushButton {{ background:{t['control_bg']}; color:{t['text']};
                          border:none; padding:4px 12px; border-radius:2px; }}
            QPushButton:hover {{ background:{t['control_hover']}; }}
            QPushButton:default {{ background:{t['selection']}; color:{t['text']}; }}
        """)

    def _populate(self):
        self.list.clear()
        for name, info in self._profiles.items():
            host = info.get('host', '')
            hostname = info.get('hostname', '')
            user = info.get('user', '')
            proto = info.get('protocol', 'SSH')
            label = name
            if hostname:
                label = f"{name}  [{hostname}]"
            item = QListWidgetItem(label)
            tip = f"[{proto}] {user}@{host}"
            if hostname and hostname != host:
                tip += f"\n(別名/ホスト名: {hostname})"
            item.setToolTip(tip)
            self.list.addItem(item)

    def _on_rename(self, item):
        old = item.text()
        new, ok = QInputDialog.getText(
            self, "名前変更", "新しい名前:", text=old,
        )
        if not ok or not new.strip() or new == old:
            return
        new = new.strip()
        if new in self._profiles:
            QMessageBox.warning(self, "重複", f"「{new}」は既に存在します。")
            return
        new_map = {}
        for k, v in self._profiles.items():
            new_map[new if k == old else k] = v
        self._profiles = new_map
        item.setText(new)

    def _on_rename_selected(self):
        item = self.list.currentItem()
        if item:
            self._on_rename(item)

    def _on_delete(self):
        item = self.list.currentItem()
        if not item:
            return
        name = item.text()
        ans = QMessageBox.question(
            self, "削除確認", f"プロファイル「{name}」を削除しますか？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        self._profiles.pop(name, None)
        self.list.takeItem(self.list.row(item))

    def accept(self):
        names_in_order = [self.list.item(i).text() for i in range(self.list.count())]
        reordered = {n: self._profiles[n] for n in names_in_order if n in self._profiles}
        _save_profiles(reordered)
        super().accept()


# ---------------------------------------------------------------------------
# アラートメール解析
# ---------------------------------------------------------------------------

def parse_alert_email(text: str) -> dict:
    """製造系アラートメールから ノード/プロセス/時刻/ロット/装置/工程/エラーコード 等を抽出。
    `key = [value]` / `key: value` / `key   = value` のような書式を許容する。
    """
    fields: dict = {}

    def grab(pattern: str, key: str):
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            fields[key] = m.group(1).strip()

    # よくあるラベル → 統一キー
    # ※ `\s*[=:]` を必須にすることで本文中の `ロット[XXX]` 等を誤検出しない
    grab(r'(?:ノード|node|host|hostname)\s*[=:]\s*\[?\s*([^\s\]\n]+)',          'host')
    grab(r'(?:プロセス|process|service|app)\s*[=:]\s*\[?\s*([^\s\]\n]+)',        'process')
    grab(r'(?:ロット|lot|lot[_\s-]?id)\s*[=:]\s*\[?\s*([^\s\]\n]+)',             'lot')
    # 装置 (Equipment/EQ ID — 1ASETF5IKT02 / 1DRAGONCAS06 等)
    grab(r'(?:装置|equipment|eq[_\s-]?id|machine|tool)\s*[=:]\s*\[?\s*([^\s\]\n]+)', 'equipment')
    # キャリア (Carrier — M00020 等。ロット不明のアラートで重要)
    grab(r'(?:キャリア|carrier|carrier[_\s-]?id|cassette)\s*[=:]\s*\[?\s*([^\s\]\n]+)', 'carrier')
    # 大工程 / 小工程: 「小工程」内の「工程」が大工程パターンに誤マッチしないよう
    # 個別キーワードに絞る (汎用 `工程` のフォールバックは別途末尾で試行)
    grab(r'(?:大工程|process[_\s-]?step|major[_\s-]?step)\s*[=:]\s*\[?\s*([^\]\n]+?)\s*\]?\s*(?:\n|$)', 'step_major')
    grab(r'(?:小工程|sub[_\s-]?step|minor[_\s-]?step)\s*[=:]\s*\[?\s*([^\]\n]+?)\s*\]?\s*(?:\n|$)', 'step_minor')
    # 大工程が取れなかった時のみ、汎用の「工程」「step」を試す (誤検出回避)
    if 'step_major' not in fields:
        m = re.search(
            r'(?<![大小])工程\s*[=:]\s*\[?\s*([^\]\n]+?)\s*\]?\s*(?:\n|$)', text
        )
        if m:
            fields['step_major'] = m.group(1).strip()

    # 時刻: 2026/05/26 08:32:57 / 2026-05-26T08:32:57 等
    m_ts = re.search(
        r'(\d{4}[-/]\d{2}[-/]\d{2}[T\s]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?)', text
    )
    if m_ts:
        fields['timestamp'] = m_ts.group(1)

    # レベル (ERROR/WARN/INFO 等)
    m_level = re.search(r'\b(ERROR|CRITICAL|FATAL|WARN(?:ING)?|INFO)\b', text)
    if m_level:
        fields['level'] = m_level.group(1).upper()

    # MES エラーコード (例: MES00059) — 本文先頭付近に出現することが多い
    m_code = re.search(r'\b(MES\d{3,6}|E\d{4,6}|ERR-?\d{3,6})\b', text)
    if m_code:
        fields['error_code'] = m_code.group(1)

    # サマリ (本文の最初の文/行) — 検索キーワードのフォールバック用
    # 「ERROR」「WARNING」等のレベル行を除いた最初の意味ある行を拾う
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        # レベルだけの行はスキップ
        if re.fullmatch(r'(ERROR|CRITICAL|FATAL|WARN(?:ING)?|INFO)', s, re.IGNORECASE):
            continue
        fields['summary'] = s[:200]
        break

    return fields


def _parse_rotation_dt(filename: str):
    """ローテーションログ名から日時を抽出する。
      ctlsvr1.log.20260528064257 → 2026-05-28 06:42:57
      messvr.log.20260504        → 2026-05-04 00:00:00
      messvr.log-20260504        → 同上
    現行ログ (suffix無し) や日時が読めない場合は None。
    """
    from datetime import datetime
    m = re.search(r'\.log[._-]?(\d{8,14})\b', filename, re.IGNORECASE)
    if not m:
        return None
    d = m.group(1)
    try:
        y, mo, da = int(d[0:4]), int(d[4:6]), int(d[6:8])
        h = int(d[8:10]) if len(d) >= 10 else 0
        mi = int(d[10:12]) if len(d) >= 12 else 0
        s = int(d[12:14]) if len(d) >= 14 else 0
        return datetime(y, mo, da, h, mi, s)
    except Exception:
        return None


def _parse_alert_dt(ts: str):
    """アラートの時刻文字列を datetime に変換。失敗時 None。
    例: '2026/05/28 16:29:43' / '2026-05-28T16:29:43'
    """
    if not ts:
        return None
    from datetime import datetime
    m = re.search(
        r'(\d{4})[-/](\d{2})[-/](\d{2})[T\s](\d{2}):(\d{2}):(\d{2})', ts
    )
    if not m:
        return None
    try:
        return datetime(*(int(g) for g in m.groups()))
    except Exception:
        return None


def _pick_log_for_alert(filenames: list[str], alert_dt):
    """アラート時刻 alert_dt を含む可能性が最も高いログ名を返す。

    ローテーション名の日時 = そのファイルが切り替わった (= その時刻までの
    ログを格納している) 時刻とみなす。よって alert_dt を含むのは
    「rotation日時 >= alert_dt のうち最小」のファイル。
    該当が無ければ (= alert が最後のローテーション以降) 現行ログ (.log)。
    現行ログも無ければ最新のローテーション。
    """
    if not alert_dt or not filenames:
        return None
    rotated = []   # (dt, filename)
    current = []   # 現行ログ (.log で終わる、日時サフィックス無し)
    for fn in filenames:
        dt = _parse_rotation_dt(fn)
        if dt is None:
            if fn.lower().endswith('.log'):
                current.append(fn)
        else:
            rotated.append((dt, fn))
    # alert_dt 以上で最小の rotation = alert を含むファイル
    after = sorted([(dt, fn) for dt, fn in rotated if dt >= alert_dt])
    if after:
        return after[0][1]
    # 全ローテーションが alert より前 → 現行ログ
    if current:
        return current[0]
    # 現行が無ければ最新のローテーション
    if rotated:
        return max(rotated, key=lambda x: x[0])[1]
    return None


class LogSelectionDialog(QDialog):
    """複数のログ候補から開くものを選ぶダイアログ。
    シングル選択で「開く」、複数選択で「選択を全て開く」が可能。"""

    def __init__(self, search_dir: str, filenames: list[str], stat_map: dict,
                 parent=None, alert_dt=None):
        super().__init__(parent)
        self.setWindowTitle("対象ログを選択")
        self.setMinimumSize(560, 380)
        self._search_dir = search_dir
        self._selected_paths: list[str] = []
        self._alert_dt = alert_dt   # アラート時刻 (datetime) — 推定に使う
        self._build_ui(filenames, stat_map)

    def _build_ui(self, filenames: list[str], stat_map: dict):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(6)

        # アラート時刻を含むと推定されるログを判定
        best = _pick_log_for_alert(filenames, self._alert_dt) if self._alert_dt else None

        head = (
            f"{self._search_dir} 配下で複数のログ候補が見つかりました。\n"
            "現在のログ + 過去ローテーション含む候補一覧です:"
        )
        if best and self._alert_dt:
            head += (
                f"\n★ = アラート時刻 ({self._alert_dt:%Y-%m-%d %H:%M:%S}) を含むと推定したログ"
            )
        lbl = QLabel(head)
        lay.addWidget(lbl)

        self.list = QListWidget()
        self.list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        from datetime import datetime
        best_row = -1
        for fn in filenames:
            st = stat_map.get(fn)
            size = getattr(st, 'st_size', 0) if st else 0
            mtime = getattr(st, 'st_mtime', 0) if st else 0
            mtime_str = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M') if mtime else '-'
            size_str = self._fmt_size(size)
            # ローテーション名から日時を取り出して併記 (あれば)
            rot = _parse_rotation_dt(fn)
            rot_str = rot.strftime('%Y-%m-%d %H:%M:%S') if rot else '(現行)'
            marker = '★ ' if fn == best else '   '
            item = QListWidgetItem(
                f"{marker}{fn:<38} {size_str:>9}  ログ切替: {rot_str}"
            )
            item.setData(Qt.ItemDataRole.UserRole, fn)
            if fn == best:
                item.setForeground(QColor("#9ED969"))
                f = item.font(); f.setBold(True); item.setFont(f)
                best_row = self.list.count()
            self.list.addItem(item)
        # 推定ログがあればそれを初期選択、無ければ先頭
        if best_row >= 0:
            self.list.setCurrentRow(best_row)
            self.list.scrollToItem(self.list.item(best_row))
        elif self.list.count():
            self.list.setCurrentRow(0)
        self.list.itemDoubleClicked.connect(self._on_open_selected)
        lay.addWidget(self.list, 1)

        hint = QLabel(
            "Ctrl/Shift クリックで複数選択 → 「選択を全て開く」"
            "  /  ★=アラート時刻を含む推定ログ"
        )
        hint.setStyleSheet("color:#888;font-size:10px;")
        lay.addWidget(hint)

        btns = QHBoxLayout()
        btns.addStretch()
        open_btn = QPushButton("📂 開く")
        open_btn.clicked.connect(self._on_open_selected)
        all_btn = QPushButton("📂 選択を全て開く")
        all_btn.clicked.connect(self._on_open_all_selected)
        cancel = QPushButton("キャンセル")
        cancel.clicked.connect(self.reject)
        btns.addWidget(open_btn)
        btns.addWidget(all_btn)
        btns.addWidget(cancel)
        lay.addLayout(btns)

        t = _theme()
        self.setStyleSheet(f"""
            QDialog {{ background:{t['bg']}; }}
            QLabel  {{ color:{t['text']}; }}
            QListWidget {{ background:{t['panel_bg']}; color:{t['text']};
                          border:1px solid {t['border']}; font-family:Consolas; font-size:11px; }}
            QListWidget::item {{ padding:3px 6px; }}
            QListWidget::item:selected {{ background:{t['selection']}; color:{t['text']}; }}
            QPushButton {{ background:{t['control_bg']}; color:{t['text']};
                          border:none; padding:5px 14px; border-radius:2px; }}
            QPushButton:hover {{ background:{t['control_hover']}; }}
        """)

    @staticmethod
    def _fmt_size(b: int) -> str:
        for unit in ('B', 'KB', 'MB', 'GB'):
            if b < 1024:
                return f"{b:.0f}{unit}"
            b /= 1024
        return f"{b:.0f}TB"

    def _full_path(self, fn: str) -> str:
        # 既に絶対パス (再帰検索の結果など) ならそのまま、相対なら search_dir 連結
        if fn.startswith('/'):
            return fn
        return f"{self._search_dir}/{fn}"

    def _on_open_selected(self):
        item = self.list.currentItem()
        if not item:
            return
        fn = item.data(Qt.ItemDataRole.UserRole)
        self._selected_paths = [self._full_path(fn)]
        self.accept()

    def _on_open_all_selected(self):
        items = self.list.selectedItems()
        if not items:
            return
        self._selected_paths = [
            self._full_path(it.data(Qt.ItemDataRole.UserRole))
            for it in items
        ]
        self.accept()

    def selected_paths(self) -> list[str]:
        return self._selected_paths


class LogPopup(QDialog):
    """グリッドが満杯のときにフローティングウィンドウで MiniLogViewer を表示"""

    def __init__(self, conn, path: str, server_label: str, color_idx: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{server_label} · {os.path.basename(path)}")
        self.resize(900, 500)
        # 通常のウィンドウ (X / 最大化等あり)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.Window)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.viewer = MiniLogViewer(conn, path, server_label, color_idx, self)
        # セルの ✕ ボタンはウィンドウクローズに紐づける
        self.viewer.close_requested.connect(lambda _=None: self.close())
        # 📝 ボタン: 親 MainWindow の _open_in_text_editor へ
        if parent is not None and hasattr(parent, '_open_in_text_editor'):
            self.viewer.editor_requested.connect(parent._open_in_text_editor)
        if parent is not None and hasattr(parent, '_open_selection_in_sora'):
            self.viewer.sql_selection_requested.connect(parent._open_selection_in_sora)
        lay.addWidget(self.viewer)

    def closeEvent(self, event):
        try:
            self.viewer.stop_tail()
        except Exception:
            pass
        super().closeEvent(event)


class AlertAnalysisDialog(QDialog):
    """アラートメールをペーストして自動でサーバー特定・調査開始"""

    investigation_requested = pyqtSignal(dict)   # 抽出結果 + 'profile_name'

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("アラート調査 — メールから一発調査")
        self.setMinimumSize(640, 480)
        self._parsed: dict = {}
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)

        # 上: メール本文ペースト欄
        lay.addWidget(QLabel("アラートメールを貼り付け:"))
        self.input = QPlainTextEdit()
        self.input.setPlaceholderText(
            "例:\n"
            "ERROR\n"
            "ロット[TNF0056S00]の状態更新に失敗しました。...\n\n"
            "時刻     = [2026/05/26 08:32:57]\n"
            "プロセス = [ap2_ctlsvr2]\n"
            "ノード   = [cts7031]\n"
            "ロット   = [TNF0056S00]\n"
        )
        self.input.setMaximumHeight(180)
        lay.addWidget(self.input)

        # 解析ボタン
        parse_row = QHBoxLayout()
        parse_btn = QPushButton("🔍 解析")
        parse_btn.clicked.connect(self._on_parse)
        parse_row.addWidget(parse_btn)
        parse_row.addStretch()
        lay.addLayout(parse_row)

        # 中: 抽出結果
        lay.addWidget(QLabel("抽出結果:"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(3)
        self._result_labels: dict[str, QLabel] = {}
        for r, (key, label) in enumerate([
            ('timestamp', '時刻:'), ('level', 'レベル:'),
            ('error_code', 'エラーコード:'),
            ('host', 'ノード:'), ('process', 'プロセス:'),
            ('equipment', '装置:'),
            ('lot', 'ロット:'), ('carrier', 'キャリア:'),
            ('step_major', '大工程:'),
            ('step_minor', '小工程:'),
            ('summary', '概要:'),
        ]):
            grid.addWidget(QLabel(label), r, 0)
            v = QLabel("—")
            v.setStyleSheet("color:#888;")
            v.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            grid.addWidget(v, r, 1)
            self._result_labels[key] = v
        lay.addLayout(grid)

        # サーバープロファイル候補
        lay.addWidget(QLabel("一致するサーバープロファイル:"))
        self.profile_list = QListWidget()
        self.profile_list.setMaximumHeight(100)
        lay.addWidget(self.profile_list)

        # アクションボタン
        action_row = QHBoxLayout()
        action_row.addStretch()
        self.go_btn = QPushButton("🚀 調査開始")
        self.go_btn.setToolTip(
            "選択中のサーバープロファイルに接続して、推定ログを開き、ロットIDでフィルタ"
        )
        self.go_btn.setEnabled(False)
        self.go_btn.clicked.connect(self._on_investigate)
        action_row.addWidget(self.go_btn)
        close_btn = QPushButton("閉じる")
        close_btn.clicked.connect(self.reject)
        action_row.addWidget(close_btn)
        lay.addLayout(action_row)

        t = _theme()
        self.setStyleSheet(f"""
            QDialog {{ background:{t['bg']}; }}
            QLabel  {{ color:{t['text']}; }}
            QPlainTextEdit {{ background:{t['panel_bg']}; color:{t['text']};
                             border:1px solid {t['border']}; font-family:Consolas; }}
            QListWidget {{ background:{t['panel_bg']}; color:{t['text']};
                          border:1px solid {t['border']}; }}
            QListWidget::item {{ padding:3px 6px; }}
            QListWidget::item:selected {{ background:{t['selection']}; color:{t['text']}; }}
            QPushButton {{ background:{t['control_bg']}; color:{t['text']};
                          border:none; padding:5px 14px; border-radius:2px; }}
            QPushButton:hover {{ background:{t['control_hover']}; }}
            QPushButton:disabled {{ color:{t['text_dim']}; }}
        """)

    def _on_parse(self):
        text = self.input.toPlainText()
        if not text.strip():
            QMessageBox.information(self, "入力なし", "メール本文を貼り付けてください。")
            return
        self._parsed = parse_alert_email(text)
        # 抽出結果を表示
        for key, lbl in self._result_labels.items():
            v = self._parsed.get(key)
            if v:
                lbl.setText(v)
                lbl.setStyleSheet(f"color:{_theme()['text']};font-weight:600;")
            else:
                lbl.setText("(未検出)")
                lbl.setStyleSheet(f"color:{_theme()['text_dim']};")

        # プロファイル候補を検索
        # マッチ優先度: hostname (alert用ホスト名フィールド) > host (接続先IP/FQDN)
        self.profile_list.clear()
        target = self._parsed.get('host', '').lower()
        profiles = _load_profiles()
        matches: list[str] = []
        if target:
            for name, info in profiles.items():
                phost = (info.get('host') or '').lower()
                pname = (info.get('hostname') or '').lower()
                # hostname (alert照合用) を最優先、なければ host
                if pname:
                    if pname == target or target in pname or pname in target:
                        matches.append(name)
                        continue
                if phost == target or target in phost or phost in target:
                    matches.append(name)
        if matches:
            for name in matches:
                info = profiles[name]
                desc = info.get('hostname') or info.get('host')
                item = QListWidgetItem(f"✓ {name}  ({desc})")
                item.setData(Qt.ItemDataRole.UserRole, name)
                self.profile_list.addItem(item)
            self.profile_list.setCurrentRow(0)
            self.go_btn.setEnabled(True)
        else:
            # 候補なし: 全プロファイルを表示 (手動選択)
            note = QListWidgetItem(
                f"✗ 「{target}」に一致するプロファイルなし — 任意で選択:"
            ) if target else QListWidgetItem("（ノード未抽出。任意で選択:）")
            note.setFlags(Qt.ItemFlag.NoItemFlags)
            note.setForeground(QColor('#FF7070'))
            self.profile_list.addItem(note)
            for name, info in profiles.items():
                desc = info.get('hostname') or info.get('host') or ''
                item = QListWidgetItem(f"  {name}  ({desc})")
                item.setData(Qt.ItemDataRole.UserRole, name)
                self.profile_list.addItem(item)
            self.go_btn.setEnabled(bool(profiles))

    def _on_investigate(self):
        item = self.profile_list.currentItem()
        if not item:
            return
        prof_name = item.data(Qt.ItemDataRole.UserRole)
        if not prof_name:
            return
        payload = dict(self._parsed)
        payload['profile_name'] = prof_name
        self.investigation_requested.emit(payload)
        self.accept()


class WorkspaceManagerDialog(QDialog):
    """ワークスペースの並べ替え/名前変更/削除を行うダイアログ"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("ワークスペース管理")
        self.setMinimumSize(420, 360)
        self._workspaces = _load_workspaces()
        self._build_ui()
        self._populate()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        hint = QLabel("ドラッグで並べ替え / ダブルクリックで名前変更")
        hint.setStyleSheet("color:#888;font-size:10px;")
        lay.addWidget(hint)

        self.list = QListWidget()
        self.list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.list.itemDoubleClicked.connect(self._on_rename)
        lay.addWidget(self.list, 1)

        # 操作ボタン
        ops = QHBoxLayout()
        rename_btn = QPushButton("✏ 名前変更")
        rename_btn.clicked.connect(self._on_rename_selected)
        delete_btn = QPushButton("🗑 削除")
        delete_btn.clicked.connect(self._on_delete)
        ops.addWidget(rename_btn)
        ops.addWidget(delete_btn)
        ops.addStretch()
        lay.addLayout(ops)

        # OK / キャンセル
        btns = QHBoxLayout()
        btns.addStretch()
        ok = QPushButton("OK")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        cancel = QPushButton("キャンセル")
        cancel.clicked.connect(self.reject)
        btns.addWidget(ok)
        btns.addWidget(cancel)
        lay.addLayout(btns)

        t = _theme()
        self.setStyleSheet(f"""
            QDialog {{ background:{t['bg']}; }}
            QLabel  {{ color:{t['text']}; }}
            QListWidget {{ background:{t['panel_bg']}; color:{t['text']};
                          border:1px solid {t['border']}; font-size:12px; }}
            QListWidget::item {{ padding:4px 6px; }}
            QListWidget::item:selected {{ background:{t['selection']}; color:{t['text']}; }}
            QPushButton {{ background:{t['control_bg']}; color:{t['text']};
                          border:none; padding:4px 12px; border-radius:2px; }}
            QPushButton:hover {{ background:{t['control_hover']}; }}
            QPushButton:default {{ background:{t['selection']}; color:{t['text']}; }}
        """)

    def _populate(self):
        self.list.clear()
        for name, ws in self._workspaces.items():
            grid = ws.get('grid', {})
            n_servers = len(ws.get('servers', []))
            r, c = grid.get('rows', 0), grid.get('cols', 0)
            item = QListWidgetItem(name)
            item.setToolTip(f"{n_servers}サーバー / グリッド {r}×{c}")
            self.list.addItem(item)

    def _on_rename(self, item):
        old = item.text()
        new, ok = QInputDialog.getText(
            self, "名前変更", "新しい名前:", text=old,
        )
        if not ok or not new.strip() or new == old:
            return
        new = new.strip()
        if new in self._workspaces:
            QMessageBox.warning(self, "重複", f"「{new}」は既に存在します。")
            return
        # 順序を保ったまま rename
        new_map = {}
        for k, v in self._workspaces.items():
            new_map[new if k == old else k] = v
        self._workspaces = new_map
        item.setText(new)

    def _on_rename_selected(self):
        item = self.list.currentItem()
        if item:
            self._on_rename(item)

    def _on_delete(self):
        item = self.list.currentItem()
        if not item:
            return
        name = item.text()
        ans = QMessageBox.question(
            self, "削除確認", f"「{name}」を削除しますか？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        self._workspaces.pop(name, None)
        self.list.takeItem(self.list.row(item))

    def accept(self):
        # リストの現在の並び順で dict を再構築
        names_in_order = [self.list.item(i).text() for i in range(self.list.count())]
        reordered = {n: self._workspaces[n] for n in names_in_order if n in self._workspaces}
        _save_workspaces(reordered)
        super().accept()


class SettingsDialog(QDialog):
    """フォントサイズとテーマの設定。OK で SETTINGS を更新・保存。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("設定")
        self.setMinimumWidth(360)
        self._build_ui()

    def _build_ui(self):
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        tabs = QTabWidget()
        tabs.addTab(self._build_display_tab(), "表示")
        tabs.addTab(self._build_migrate_tab(), "設定移行")
        lay.addWidget(tabs)

        # ボタン (タブ外共通)
        btns = QHBoxLayout()
        btns.addStretch()
        ok = QPushButton("OK")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        cancel = QPushButton("キャンセル")
        cancel.clicked.connect(self.reject)
        btns.addWidget(ok)
        btns.addWidget(cancel)
        lay.addLayout(btns)

        t = _theme()
        self.setStyleSheet(f"""
            QDialog{{background:{t['bg']};}}
            QLabel{{color:{t['text']};}}
            QCheckBox{{color:{t['text']}; padding:2px;}}
            QTabWidget::pane{{border:1px solid {t['border']};background:{t['panel_bg']};
                             top:-1px;}}
            QTabBar::tab{{background:{t['control_bg']};color:{t['text_dim']};
                         padding:5px 14px;border:1px solid {t['border']};
                         border-bottom:none;margin-right:2px;}}
            QTabBar::tab:selected{{background:{t['panel_bg']};color:{t['text']};
                                  border-bottom:1px solid {t['panel_bg']};}}
            QComboBox{{background:{t['control_bg']};color:{t['text']};
                      border:1px solid {t['border']};
                      padding:2px 4px;min-height:24px;}}
            QComboBox QAbstractItemView{{background:{t['panel_bg']};color:{t['text']};
                                        selection-background-color:{t['selection']};}}
            QPushButton{{background:{t['control_bg']};color:{t['text']};border:none;
                        padding:4px 12px;border-radius:2px;}}
            QPushButton:hover{{background:{t['control_hover']};}}
            QPushButton:default{{background:{t['selection']};color:{t['text']};}}
        """)

    def _tab_page(self):
        """タブページ用の (QWidget, QVBoxLayout) を作る共通ヘルパー。"""
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(10, 10, 10, 10)
        v.setSpacing(6)
        return page, v

    def _build_display_tab(self):
        from PyQt6.QtWidgets import QSpinBox
        page, v = self._tab_page()

        v.addWidget(self._section_label("フォントサイズ"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(2)
        self._spinners: dict[str, QSpinBox] = {}
        rows = [
            ("左サイドバー (DIRツリー):", 'tree_font_size',     7, 24),
            ("ツールバー:",                'toolbar_font_size',  7, 24),
            ("ログセル (本文):",           'log_font_size',      7, 24),
            ("ターミナル:",                'terminal_font_size', 7, 24),
        ]
        for r, (label, key, lo, hi) in enumerate(rows):
            grid.addWidget(QLabel(label), r, 0)
            container, sp = self._make_spinner(key, lo, hi)
            grid.addWidget(container, r, 1)
            self._spinners[key] = sp
        v.addLayout(grid)

        v.addWidget(self._section_label("テーマ"))
        theme_row = QHBoxLayout()
        theme_row.addWidget(QLabel("プリセット:"))
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(list(_THEME_PRESETS.keys()))
        cur_theme = SETTINGS.get('theme', 'Dark')
        i = self.theme_combo.findText(cur_theme)
        if i >= 0:
            self.theme_combo.setCurrentIndex(i)
        theme_row.addWidget(self.theme_combo, 1)
        v.addLayout(theme_row)

        v.addWidget(self._section_label("左パネル表示"))
        self.cb_quick_jump = QCheckBox("クイックジャンプ (📋ログ / 🏠ホーム / 🗂/tmp) を表示")
        self.cb_quick_jump.setChecked(bool(SETTINGS.get('show_quick_jump', True)))
        v.addWidget(self.cb_quick_jump)
        self.cb_panel_hints = QCheckBox("説明ラベル (📁 表示中のフォルダ・⚡クイック…等) を表示")
        self.cb_panel_hints.setChecked(bool(SETTINGS.get('show_panel_hints', True)))
        v.addWidget(self.cb_panel_hints)

        v.addStretch()
        # このタブ (フォント・テーマ・左パネル) のみをデフォルトに戻すボタン
        reset_row = QHBoxLayout()
        reset_row.addStretch()
        reset = QPushButton("デフォルトに戻す")
        reset.setToolTip("フォントサイズ・テーマ・左パネル表示を初期値に戻します")
        reset.clicked.connect(self._reset_defaults)
        reset_row.addWidget(reset)
        v.addLayout(reset_row)
        return page

    def _build_migrate_tab(self):
        page, v = self._tab_page()
        migrate_help = QLabel(
            "プロファイル / ワークスペース / 設定を JSON 1ファイルに出力・読込できます。\n"
            "別 PC に環境を移したい時にお使いください。"
        )
        migrate_help.setStyleSheet("color:#888; font-size:10px; padding:2px 4px;")
        migrate_help.setWordWrap(True)
        v.addWidget(migrate_help)
        migrate_row = QHBoxLayout()
        self.export_btn = QPushButton("📤 エクスポート (JSON保存)")
        self.export_btn.setToolTip("接続プロファイル / ワークスペース / UI設定を JSON に書き出す")
        self.import_btn = QPushButton("📥 インポート (JSON読込)")
        self.import_btn.setToolTip("別 PC からエクスポートした JSON を取り込む (マージ/置換選択)")
        migrate_row.addWidget(self.export_btn)
        migrate_row.addWidget(self.import_btn)
        v.addLayout(migrate_row)
        v.addStretch()
        return page

    @staticmethod
    def _section_label(text: str) -> QLabel:
        t = _theme()
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"color:{t['text_dim']}; background:{t['toolbar_bg']};"
            f"font-weight:600; padding:4px 6px;"
        )
        return lbl

    @staticmethod
    def _make_spinner(key: str, lo: int, hi: int):
        """[値] [△] [▽] の横並びスピナー (コンパクト)。"""
        from PyQt6.QtWidgets import QSpinBox  # 念のため
        t = _theme()
        container = QWidget()
        h = QHBoxLayout(container)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        sp = QSpinBox()
        sp.setRange(lo, hi)
        sp.setValue(int(SETTINGS.get(key, _DEFAULT_SETTINGS[key])))
        sp.setSuffix(" px")
        sp.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        sp.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sp.setStyleSheet(
            f"QSpinBox{{background:{t['panel_bg']};color:{t['text']};"
            f"border:1px solid {t['border']};"
            f"border-right:none;padding:1px 4px;}}"
        )
        sp.setFixedSize(60, 22)

        btn_style = (
            f"QPushButton{{background:{t['control_bg']};color:{t['text']};"
            f"border:1px solid {t['border']};"
            f"padding:0;margin:0;font-size:10px;font-weight:bold;}}"
            f"QPushButton:hover{{background:{t['control_hover']};}}"
            f"QPushButton:pressed{{background:{t['selection']};color:{t['text']};}}"
        )

        up = QPushButton("△")
        up.setFixedSize(20, 22)
        up.setAutoRepeat(True)
        up.setAutoRepeatInterval(80)
        up.setStyleSheet(btn_style)
        up.setToolTip("増やす")
        up.clicked.connect(lambda: sp.stepBy(+1))

        down = QPushButton("▽")
        down.setFixedSize(20, 22)
        down.setAutoRepeat(True)
        down.setAutoRepeatInterval(80)
        down.setStyleSheet(btn_style)
        down.setToolTip("減らす")
        down.clicked.connect(lambda: sp.stepBy(-1))

        h.addWidget(sp)
        h.addWidget(up)
        h.addWidget(down)
        h.addStretch()
        return container, sp

    def _reset_defaults(self):
        for k, sp in self._spinners.items():
            sp.setValue(int(_DEFAULT_SETTINGS[k]))
        i = self.theme_combo.findText(_DEFAULT_SETTINGS['theme'])
        if i >= 0:
            self.theme_combo.setCurrentIndex(i)
        self.cb_quick_jump.setChecked(bool(_DEFAULT_SETTINGS['show_quick_jump']))
        self.cb_panel_hints.setChecked(bool(_DEFAULT_SETTINGS['show_panel_hints']))

    def accept(self):
        for k, sp in self._spinners.items():
            SETTINGS[k] = sp.value()
        SETTINGS['theme'] = self.theme_combo.currentText()
        SETTINGS['show_quick_jump']  = bool(self.cb_quick_jump.isChecked())
        SETTINGS['show_panel_hints'] = bool(self.cb_panel_hints.isChecked())
        try:
            _save_settings(SETTINGS)
        except Exception as e:
            QMessageBox.warning(self, "保存エラー", str(e))
        super().accept()


# ---------------------------------------------------------------------------
# 対話的ターミナル
# ---------------------------------------------------------------------------

class TerminalReader(QThread):
    new_text = pyqtSignal(str)
    error    = pyqtSignal(str)

    def __init__(self, channel):
        super().__init__()
        self._chan = channel
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            while not self._stop:
                if self._chan.recv_ready(0.1):
                    data = self._chan.recv(4096)
                    if not data:
                        time.sleep(0.05)
                        continue
                    self.new_text.emit(data.decode('utf-8', errors='replace'))
                else:
                    time.sleep(0.05)
        except Exception as e:
            self.error.emit(str(e))


_ANSI_ESCAPE_RE = re.compile(r'\x1b\[[0-9;?]*[a-zA-Z]')


class TerminalDialog(QDialog):
    """SSH/Telnet で対話的にコマンドを送れるターミナル。"""

    def __init__(self, conn, parent=None):
        super().__init__(parent)
        proto = getattr(conn, 'protocol', 'ssh').upper()
        self.setWindowTitle(f"ターミナル [{proto}] — {conn.label}")
        self.resize(820, 520)
        self._conn = conn
        self._chan = None
        self._reader: TerminalReader | None = None
        self._history: list[str] = []
        self._hist_idx = 0
        self._build_ui()
        self._open_channel()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(3)

        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        lay.addWidget(self.output, 1)

        row = QHBoxLayout()
        row.setSpacing(3)
        self.input = QLineEdit()
        self.input.setPlaceholderText("コマンド (Enter で送信 / ↑↓で履歴)")
        self.input.returnPressed.connect(self._send)
        self.input.installEventFilter(self)
        row.addWidget(self.input, 1)

        send_btn = QPushButton("送信")
        send_btn.clicked.connect(self._send)
        row.addWidget(send_btn)

        ctrlc_btn = QPushButton("Ctrl+C")
        ctrlc_btn.setToolTip("中断シグナル送信 (0x03)")
        ctrlc_btn.clicked.connect(lambda: self._send_raw(b'\x03'))
        row.addWidget(ctrlc_btn)

        clear_btn = QPushButton("クリア")
        clear_btn.clicked.connect(self.output.clear)
        row.addWidget(clear_btn)

        lay.addLayout(row)

        self.setStyleSheet("""
            QDialog{background:#1a1a1a;}
            QPushButton{background:#3a3a3a;color:#a9b7c6;border:none;
                        padding:3px 10px;border-radius:2px;font-size:11px;}
            QPushButton:hover{background:#4a4a4a;}
        """)

        self.apply_settings()

    def apply_settings(self):
        fs = SETTINGS.get('terminal_font_size', 10)
        t = _theme()
        self.output.setFont(QFont("Consolas", fs))
        self.output.setStyleSheet(
            f"background:#0e0e0e;color:#d0d0d0;border:1px solid {t['border']};"
            f"selection-background-color:{t['selection']};"
        )
        self.input.setStyleSheet(
            f"background:#1e1e1e;color:#d0d0d0;border:1px solid {t['border']};padding:3px;"
            f"font-family:Consolas; font-size:{fs + 1}px;"
        )

    def eventFilter(self, obj, event):
        if obj is self.input and event.type() == event.Type.KeyPress:
            if event.key() == Qt.Key.Key_Up:
                self._history_step(-1)
                return True
            if event.key() == Qt.Key.Key_Down:
                self._history_step(+1)
                return True
        return super().eventFilter(obj, event)

    def _history_step(self, delta: int):
        if not self._history:
            return
        self._hist_idx = max(0, min(len(self._history), self._hist_idx + delta))
        if self._hist_idx >= len(self._history):
            self.input.setText('')
        else:
            self.input.setText(self._history[self._hist_idx])

    def _open_channel(self):
        try:
            self._chan = self._conn.open_shell_channel()
        except Exception as e:
            QMessageBox.critical(self, "ターミナルを開けません", str(e))
            QTimer.singleShot(0, self.reject)
            return
        self._reader = TerminalReader(self._chan)
        self._reader.new_text.connect(self._append)
        self._reader.error.connect(lambda e: self._append(f"\n[エラー] {e}\n"))
        self._reader.start()
        # 入力欄にフォーカスを当て、即座にタイプ可能にする
        QTimer.singleShot(50, self.input.setFocus)

    def showEvent(self, event):
        super().showEvent(event)
        self.input.setFocus()

    def _append(self, text: str):
        text = _ANSI_ESCAPE_RE.sub('', text)
        text = text.replace('\r\n', '\n').replace('\r', '')
        self.output.moveCursor(QTextCursor.MoveOperation.End)
        self.output.insertPlainText(text)
        sb = self.output.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _send(self):
        if not self._chan:
            self._append("\n[エラー] チャネルが閉じています\n")
            return
        cmd = self.input.text()
        # SSH PTY は \n で十分、Telnet は \r\n が標準
        eol = b'\r\n' if getattr(self._conn, 'protocol', 'ssh') == 'telnet' else b'\n'
        try:
            self._chan.send(cmd.encode('utf-8') + eol)
        except Exception as e:
            self._append(f"\n[送信エラー] {e}\n")
            return
        if cmd.strip():
            if not self._history or self._history[-1] != cmd:
                self._history.append(cmd)
            self._hist_idx = len(self._history)
        self.input.clear()
        self.input.setFocus()

    def _send_raw(self, data: bytes):
        if not self._chan:
            self._append("\n[エラー] チャネルが閉じています\n")
            return
        try:
            self._chan.send(data)
        except Exception as e:
            self._append(f"\n[送信エラー] {e}\n")

    def closeEvent(self, event):
        if self._reader:
            self._reader.stop()
            self._reader.wait(2000)
        if self._chan:
            self._chan.close()
        super().closeEvent(event)


# ---------------------------------------------------------------------------
# メインウィンドウ
# ---------------------------------------------------------------------------

_GRID_PRESETS = {
    "1×1": (1, 1), "1×2": (1, 2), "1×3": (1, 3), "1×4": (1, 4), "1×5": (1, 5), "1×6": (1, 6),
    "2×1": (2, 1), "2×2": (2, 2), "2×3": (2, 3), "2×4": (2, 4), "2×5": (2, 5), "2×6": (2, 6),
    "3×1": (3, 1), "3×2": (3, 2), "3×3": (3, 3), "3×4": (3, 4), "3×5": (3, 5), "3×6": (3, 6),
    "4×3": (4, 3), "4×4": (4, 4), "4×5": (4, 5), "4×6": (4, 6),
    "5×1": (5, 1), "5×2": (5, 2), "5×3": (5, 3),
    "6×1": (6, 1), "6×2": (6, 2), "6×3": (6, 3),
}


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Multi-Server Log Viewer  v{__version__}")
        self.resize(1600, 900)
        self._panels: list[ServerPanel] = []
        self._terminals: list = []
        self._log_popups: list = []   # フローティング表示の LogPopup
        self._setup_ui()
        self._apply_theme()

    # ------------------------------------------------------------------ UI

    def _apply_toolbar_style(self):
        """ツールバーの自前スタイルをテーマから生成して適用 (テーマ変更で再適用)。"""
        tb = getattr(self, '_toolbar', None)
        if tb is None:
            return
        t = _theme()
        tb.setStyleSheet(
            f"QToolBar {{ background:{t['toolbar_bg']}; border:none; spacing:3px; padding:4px 6px; }}"
            f"QToolBar::separator {{ background:{t['border']}; width:1px; margin:4px 6px; }}"
            f"QToolBar QLabel {{ color:{t['text_dim']}; padding:0 4px; font-size:11px; }}"
            f"QToolBar QPushButton, QToolBar QToolButton {{"
            f"  background:{t['control_bg']}; color:{t['text']}; border:1px solid {t['border']};"
            f"  padding:5px 10px; border-radius:4px; font-size:12px;"
            f"}}"
            f"QToolBar QPushButton:hover, QToolBar QToolButton:hover {{"
            f"  background:{t['control_hover']}; border:1px solid {t['border']};"
            f"}}"
            f"QToolBar QPushButton:pressed, QToolBar QToolButton:pressed {{"
            f"  background:{t['selection']}; border:1px solid {t['selection']};"
            f"}}"
            f"QToolBar QPushButton::menu-indicator,"
            f"QToolBar QToolButton::menu-indicator {{ width:0px; image:none; }}"
            f"QToolBar QPushButton[primary='true'] {{"
            f"  background:#3a6e3a; color:#e0f0e0; border:1px solid #4a8e4a;"
            f"}}"
            f"QToolBar QPushButton[primary='true']:hover {{"
            f"  background:#4a8e4a; border:1px solid #5aa05a;"
            f"}}"
            f"QToolBar QPushButton[danger='true'] {{"
            f"  background:#c0392b; color:#ffffff; border:1px solid #e05545; font-weight:600;"
            f"}}"
            f"QToolBar QPushButton[danger='true']:hover {{"
            f"  background:#e0432f; border:1px solid #ff6b5a;"
            f"}}"
            f"QToolBar QComboBox, QToolBar QLineEdit {{"
            f"  background:{t['panel_bg']}; color:{t['text']}; border:1px solid {t['border']};"
            f"  padding:3px 6px; border-radius:3px; font-size:12px;"
            f"}}"
            f"QToolBar QComboBox:focus, QToolBar QLineEdit:focus {{"
            f"  border:1px solid {t['selection']};"
            f"}}"
        )

    def _setup_ui(self):
        # ── ツールバー (アイコン+ラベル統一スタイル) ──────────────────
        tb = QToolBar("ツールバー")
        tb.setMovable(False)
        tb.setIconSize(QSize(18, 18))
        self._toolbar = tb
        # ツールバー自前スタイル (テーマ変更時に _apply_theme から再適用される)
        self._apply_toolbar_style()
        self.addToolBar(tb)

        # ── グリッド ──────────────────────────────────────────────────
        tb.addWidget(QLabel("📐 グリッド"))
        self.grid_combo = QComboBox()
        self.grid_combo.addItems(_GRID_PRESETS.keys())
        self.grid_combo.setCurrentText("2×2")
        self.grid_combo.setFixedWidth(70)
        self.grid_combo.setToolTip("ログを並べるセル数を変更 (例: 2×2 = 4セル)")
        self.grid_combo.currentTextChanged.connect(self._on_grid_change)
        tb.addWidget(self.grid_combo)

        tb.addSeparator()

        # ── Tail 制御 ─────────────────────────────────────────────────
        btn_all_tail = QPushButton("▶ 全Tail開始")
        btn_all_tail.setProperty("primary", True)
        btn_all_tail.setToolTip("全セルで Tail -F を開始 (新しい行が自動追従)")
        btn_all_tail.clicked.connect(lambda: self.grid.start_all_tail())
        tb.addWidget(btn_all_tail)

        btn_stop_all = QPushButton("■ 全停止")
        btn_stop_all.setProperty("danger", True)
        btn_stop_all.setToolTip("全セルの Tail -F を停止")
        btn_stop_all.clicked.connect(lambda: self.grid.stop_all_tail())
        tb.addWidget(btn_stop_all)

        tb.addSeparator()

        # ── 共通フィルタ ──────────────────────────────────────────────
        tb.addWidget(QLabel("🔎 共通フィルタ"))
        self.global_filter = QLineEdit()
        self.global_filter.setPlaceholderText("全セルに適用するキーワード/正規表現")
        self.global_filter.setMinimumWidth(180)
        self.global_filter.setToolTip(
            "検索文字列または正規表現 — 「適用」ボタンで全セルに反映"
        )
        tb.addWidget(self.global_filter)

        self.global_level = QComboBox()
        self.global_level.addItems(["ALL", "ERROR+", "WARN+", "INFO+"])
        self.global_level.setFixedWidth(80)
        self.global_level.setToolTip(
            "ログレベルでフィルタ:\n"
            "  ALL    = 全行\n"
            "  ERROR+ = ERROR/CRITICAL/FATAL\n"
            "  WARN+  = WARN以上\n"
            "  INFO+  = INFO以上"
        )
        tb.addWidget(self.global_level)

        apply_btn = QPushButton("適用")
        apply_btn.setToolTip("共通フィルタとレベルを全セルに反映")
        apply_btn.clicked.connect(self._apply_global_filter)
        tb.addWidget(apply_btn)

        tb.addSeparator()

        # ── 接続 ──────────────────────────────────────────────────────
        add_server_btn = QPushButton("＋ サーバー接続")
        add_server_btn.setProperty("primary", True)
        add_server_btn.setToolTip("新しいサーバーに SSH または Telnet で接続 (最大6台)")
        add_server_btn.clicked.connect(self._add_server)
        tb.addWidget(add_server_btn)

        tb.addSeparator()

        # ── ワークスペース ────────────────────────────────────────────
        tb.addWidget(QLabel("💼 ワークスペース"))
        self.ws_combo = QComboBox()
        self.ws_combo.setMinimumWidth(150)
        self.ws_combo.setToolTip("保存済みワークスペース (サーバー接続+ログ構成のセット)")
        tb.addWidget(self.ws_combo)
        self._refresh_workspace_combo()

        from PyQt6.QtWidgets import QMenu
        ws_act_btn = QPushButton("操作 ▾")
        ws_act_btn.setToolTip("ワークスペース操作 (読込/保存/管理)")
        ws_menu = QMenu(ws_act_btn)
        act_load = ws_menu.addAction("📂 読込 (選択中を開く)")
        act_save = ws_menu.addAction("💾 現在の状態を保存...")
        ws_menu.addSeparator()
        act_mgr  = ws_menu.addAction("⚙ 管理 (並替/改名/削除)...")
        act_load.triggered.connect(self._load_workspace)
        act_save.triggered.connect(self._save_workspace)
        act_mgr.triggered.connect(self._manage_workspaces)
        ws_act_btn.setMenu(ws_menu)
        tb.addWidget(ws_act_btn)

        # 右寄せ用スペーサー (背景をツールバー色に合わせて黒浮きを防ぐ / テーマ変更で更新)
        self._tb_spacer = QWidget()
        self._tb_spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._tb_spacer.setStyleSheet(f"background:{_theme()['toolbar_bg']};")
        tb.addWidget(self._tb_spacer)

        # ── 解析・運用ツール (右寄せ) ─────────────────────────────────
        alert_btn = QPushButton("🚨 アラート調査")
        alert_btn.setToolTip(
            "運用アラートメールを貼り付けて、該当サーバー/ログを自動で開く"
        )
        alert_btn.clicked.connect(self._open_alert_analysis)
        tb.addWidget(alert_btn)

        tb.addSeparator()

        # 設定 (📦 移行は設定ダイアログ内に統合した)
        settings_btn = QPushButton("⚙ 設定")
        settings_btn.setToolTip("設定: フォントサイズ・テーマ・設定移行 (Export/Import)")
        settings_btn.clicked.connect(self._open_settings)
        tb.addWidget(settings_btn)

        # ── メイン分割 ────────────────────────────────────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # 左：サーバーパネル群（縦に並べる）
        left = QWidget()
        left.setMinimumWidth(180)
        left.setMaximumWidth(320)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(0)

        self.panel_splitter = QSplitter(Qt.Orientation.Vertical)
        self.panel_splitter.setHandleWidth(3)

        self._no_server_label = QLabel(
            "「＋ サーバー接続」で\nLinuxサーバーに接続してください"
        )
        self._no_server_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._no_server_label.setStyleSheet("color:#404040; padding:12px; font-size:11px;")
        self._no_server_label.setWordWrap(True)
        self.panel_splitter.addWidget(self._no_server_label)
        ll.addWidget(self.panel_splitter, 1)
        splitter.addWidget(left)

        # 右：グリッド
        self.grid = LogGrid(2, 2)
        splitter.addWidget(self.grid)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([260, 1340])

        self.setCentralWidget(splitter)

        # ステータスバー
        self._status = QLabel("準備完了")
        self.statusBar().addWidget(self._status)

    # ---------------------------------------------------------------- 接続管理

    def _add_server(self):
        if len(self._panels) >= 6:
            QMessageBox.warning(self, "警告", "最大6サーバーまで同時接続できます。")
            return
        dlg = SSHConnectDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        info = dlg.get_info()
        proto = info.get('protocol', 'SSH')
        conn = TelnetConnection() if proto == 'Telnet' else SSHConnection()
        self._status.setText(f"接続中 ({proto}): {info['host']}...")
        QApplication.processEvents()
        try:
            conn.connect(info['host'], info['port'], info['user'],
                         info['password'], info.get('key_path', ''))
            color_idx  = len(self._panels)
            # 接続時の初期DIRは設定済みの log_dir (📌で保存した初期値) を使う。
            # 前回切断時DIRの自動復元 (last_dir) は廃止した。
            log_dir = info.get('log_dir', '/var/log') or '/var/log'
            panel = ServerPanel(conn, color_idx, log_dir, self)
            panel.file_open_requested.connect(self._open_log)
            panel.edit_open_requested.connect(self._open_in_text_editor)
            panel.disconnect_requested.connect(self._remove_server)
            panel.save_dir_requested.connect(self._save_log_dir)
            panel.terminal_requested.connect(self._open_terminal)
            # プロファイル名を panel/conn に記憶させてDIR更新・DB実行で使う
            panel._profile_name = dlg.combo.currentText()
            try:
                conn._profile_name = dlg.combo.currentText()
            except Exception:
                pass
            panel.refresh_header_label()
            self._panels.append(panel)
            # 初回は placeholder を除去
            if self._no_server_label:
                self.panel_splitter.widget(0).hide()
                self._no_server_label = None
            self.panel_splitter.addWidget(panel)
            self._status.setText(f"接続済み: {conn.label}  ({len(self._panels)}台)")
        except Exception as e:
            QMessageBox.critical(self, "接続エラー", str(e))
            self._status.setText("接続失敗")

    def _remove_server(self, panel: ServerPanel):
        # このサーバーのコネクションを使っているリソースを先にきれいに停止
        closed_cells = 0
        # 1. このサーバー宛のログセルを閉じる (内部で stop_tail も走る)
        for slot in self.grid._slots:
            v = slot.viewer()
            if v and getattr(v, 'conn', None) is panel.conn:
                slot.clear()
                closed_cells += 1
        # 2. このサーバー宛のターミナルを閉じる
        for dlg in list(self._terminals):
            if getattr(dlg, '_conn', None) is panel.conn:
                try:
                    dlg.close()
                except Exception:
                    pass
        # 3. コネクション切断 (SSH なら logout / Telnet なら socket close)
        panel.conn.disconnect()
        self._panels.remove(panel)
        panel.deleteLater()
        suffix = f"  ログセル {closed_cells} 個も閉じました" if closed_cells else ""
        self._status.setText(f"切断  残 {len(self._panels)} 台{suffix}")

    def _open_terminal(self, panel: ServerPanel):
        dlg = TerminalDialog(panel.conn, self)
        self._terminals.append(dlg)
        dlg.destroyed.connect(lambda _=None, d=dlg: self._terminals.remove(d) if d in self._terminals else None)
        dlg.show()  # 非モーダル — 複数同時オープン可

    # ------------------------------------------------ ワークスペース (定型ログイン)

    def _refresh_workspace_combo(self):
        """保存済みワークスペース一覧を JSON 保存順で再読込してコンボに反映"""
        if not hasattr(self, 'ws_combo'):
            return
        cur = self.ws_combo.currentText()
        self.ws_combo.blockSignals(True)
        self.ws_combo.clear()
        ws = _load_workspaces()
        # JSON の dict 順 (=保存順 / 管理ダイアログで並べ替え可) で表示
        for name in ws.keys():
            self.ws_combo.addItem(name)
        if cur:
            i = self.ws_combo.findText(cur)
            if i >= 0:
                self.ws_combo.setCurrentIndex(i)
        self.ws_combo.blockSignals(False)

    def _capture_workspace(self) -> dict:
        """現在の状態をワークスペースdictに変換"""
        # サーバーごとに開いているファイルを集計
        servers: list[dict] = []
        for panel in self._panels:
            profile = getattr(panel, '_profile_name', '-- 新規 --')
            if profile == '-- 新規 --':
                continue  # プロファイル未保存のサーバーはスキップ
            files = []
            for v in self.grid.viewers():
                if getattr(v, 'conn', None) is panel.conn:
                    files.append(v.filepath)
            servers.append({'profile': profile, 'files': files})
        return {
            'grid': {'rows': self.grid._rows, 'cols': self.grid._cols},
            'servers': servers,
        }

    def _save_workspace(self):
        if not self._panels:
            QMessageBox.information(self, "保存できません",
                "サーバーに1台も接続していません。先に接続してから保存してください。")
            return
        # プロファイル名がない (新規) サーバーがあれば警告
        no_profile = [p for p in self._panels
                      if getattr(p, '_profile_name', '-- 新規 --') == '-- 新規 --']
        if no_profile:
            QMessageBox.warning(self, "プロファイル必須",
                f"プロファイルを保存していないサーバーが {len(no_profile)} 台あります。\n"
                "接続ダイアログの「保存」ボタンでプロファイルを作成してください。\n"
                "そのサーバーはワークスペースに含まれません。")

        cur = self.ws_combo.currentText()
        name, ok = QInputDialog.getText(
            self, "ワークスペースを保存", "名前:", text=cur or ''
        )
        if not ok or not name.strip():
            return
        name = name.strip()

        all_ws = _load_workspaces()
        if name in all_ws:
            ans = QMessageBox.question(
                self, "上書き確認",
                f"「{name}」は既に存在します。上書きしますか？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if ans != QMessageBox.StandardButton.Yes:
                return

        snapshot = self._capture_workspace()
        all_ws[name] = snapshot
        _save_workspaces(all_ws)
        self._refresh_workspace_combo()
        self.ws_combo.setCurrentText(name)
        self._status.setText(
            f"💾 ワークスペース「{name}」を保存 "
            f"({len(snapshot['servers'])}サーバー / グリッド {snapshot['grid']['rows']}×{snapshot['grid']['cols']})"
        )

    def _manage_workspaces(self):
        """ワークスペース管理ダイアログを開く"""
        dlg = WorkspaceManagerDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._refresh_workspace_combo()
            self._status.setText("ワークスペースを更新しました")

    def _load_workspace(self):
        name = self.ws_combo.currentText()
        if not name:
            QMessageBox.information(self, "選択なし", "読み込むワークスペースを選んでください。")
            return
        all_ws = _load_workspaces()
        ws = all_ws.get(name)
        if not ws:
            QMessageBox.warning(self, "見つかりません", f"ワークスペース「{name}」が見つかりません。")
            return

        # 確認
        if self._panels:
            ans = QMessageBox.question(
                self, "確認",
                f"現在の {len(self._panels)} サーバー接続を切断して "
                f"「{name}」を読み込みますか？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if ans != QMessageBox.StandardButton.Yes:
                return

        # 1. 既存接続を全切断
        for panel in list(self._panels):
            self._remove_server(panel)
        self._panels.clear()

        # 2. グリッドサイズ復元
        grid = ws.get('grid', {})
        rows = int(grid.get('rows', 2))
        cols = int(grid.get('cols', 2))
        # コンボの該当プリセットを設定（無ければ近いものに）
        preset_key = f"{rows}×{cols}"
        i = self.grid_combo.findText(preset_key)
        if i >= 0:
            self.grid_combo.setCurrentIndex(i)
        else:
            self.grid.set_size(rows, cols)

        # 3. 各サーバーをプロファイル経由で接続 → 各ログを開く
        profiles = _load_profiles()
        connected = 0
        failed = []
        opened_files = 0
        for srv in ws.get('servers', []):
            prof_name = srv.get('profile')
            files = srv.get('files', [])
            info = profiles.get(prof_name)
            if not info:
                failed.append(f"{prof_name} (プロファイル削除済み)")
                continue
            try:
                conn = self._connect_from_profile(prof_name, info)
                # この conn の color_idx は self._panels.index で取れる
                panel = self._panels[-1]
                for fp in files:
                    self._open_log(conn, fp, panel.color_idx)
                    opened_files += 1
                connected += 1
            except Exception as e:
                failed.append(f"{prof_name}: {e}")

        msg = f"ワークスペース「{name}」読込完了: {connected}サーバー / {opened_files}ログ"
        if failed:
            msg += f" / 失敗 {len(failed)}件"
            QMessageBox.warning(self, "一部失敗",
                "以下のサーバーは接続できませんでした:\n\n" + "\n".join(failed))
        self._status.setText(msg)

    def _connect_from_profile(self, prof_name: str, info: dict):
        """プロファイル情報からサーバーパネルを作成・登録する。
        パスワード未保存ならプロンプト。"""
        if len(self._panels) >= 6:
            raise RuntimeError("最大6サーバーまで")
        proto = info.get('protocol', 'SSH')
        host = info.get('host', '')
        port = int(info.get('port') or (23 if proto == 'Telnet' else 22))
        user = info.get('user', '')
        password = info.get('password', '')
        key_path = info.get('key_path', '')
        # 設定済みの初期DIR (log_dir) を使う (前回DIRの自動復元は廃止)
        log_dir = (info.get('log_dir') or '/var/log') or '/var/log'

        if not password and not (key_path and proto == 'SSH'):
            password, ok = QInputDialog.getText(
                self, f"パスワード入力: {prof_name}",
                f"{user}@{host} のパスワード:",
                QLineEdit.EchoMode.Password,
            )
            if not ok:
                raise RuntimeError("パスワード入力キャンセル")

        conn = TelnetConnection() if proto == 'Telnet' else SSHConnection()
        conn.connect(host, port, user, password, key_path)
        color_idx = len(self._panels)
        panel = ServerPanel(conn, color_idx, log_dir, self)
        panel.file_open_requested.connect(self._open_log)
        panel.edit_open_requested.connect(self._open_in_text_editor)
        panel.disconnect_requested.connect(self._remove_server)
        panel.save_dir_requested.connect(self._save_log_dir)
        panel.terminal_requested.connect(self._open_terminal)
        panel._profile_name = prof_name
        try:
            conn._profile_name = prof_name
        except Exception:
            pass
        panel.refresh_header_label()
        self._panels.append(panel)
        if self._no_server_label:
            self.panel_splitter.widget(0).hide()
            self._no_server_label = None
        self.panel_splitter.addWidget(panel)
        return conn

    # ------------------------------------------------ テキストエディタで開く

    def _open_in_text_editor(self, conn, remote_path: str, search: str = ''):
        """リモートファイルをローカルにダウンロード → Sora Editor を起動。
        - SSH: SFTP でバイナリ取得 / Telnet: base64 経由 / .gz は自動解凍
        - search 指定時は Sora Editor 起動時に検索バー自動表示 (--search)
        """
        import tempfile
        import subprocess
        import gzip

        base = os.path.basename(remote_path)
        is_gz = base.lower().endswith('.gz')
        local_name = base[:-3] if is_gz else base
        # ホスト名を含めてユニークな保存先に
        host_tag = (getattr(conn, 'label', 'remote') or 'remote').replace('@', '_').replace('/', '_')
        tmp_dir = os.path.join(tempfile.gettempdir(), 'ssh_log_viewer', host_tag)
        os.makedirs(tmp_dir, exist_ok=True)
        local_path = os.path.join(tmp_dir, local_name)

        self._status.setText(f"ダウンロード中: {remote_path}...")
        QApplication.processEvents()
        try:
            data = conn.download_bytes(remote_path)
            if is_gz:
                try:
                    data = gzip.decompress(data)
                except Exception as e:
                    QMessageBox.warning(self, "解凍エラー",
                        f"{base} の gzip 解凍に失敗しました:\n{e}\n圧縮ファイルのまま開きます。")
            with open(local_path, 'wb') as f:
                f.write(data)
        except Exception as e:
            QMessageBox.critical(self, "ダウンロードエラー", str(e))
            self._status.setText("ダウンロード失敗")
            return

        # DB実行ダイアログの初期プロファイルとして使う接続プロファイル名
        profile_name = getattr(conn, '_profile_name', '') or ''

        if self._launch_sora(local_path, search=search, profile_name=profile_name):
            suffix = f" (検索: {search})" if search else ""
            self._status.setText(f"📝 Sora Editor で開きました: {local_name}{suffix}")

    def _launch_sora(self, local_path: str, *, search: str = '',
                     profile_name: str = '', sql_extract: bool = False) -> bool:
        """Sora Editor を起動 (EXE版/スクリプト版を自動判別)。
        - search: 起動後に検索バーへ自動入力
        - profile_name: DB実行ダイアログの初期プロファイル
        - sql_extract: 起動直後に SQL抽出ダイアログを自動で開く
        成功時 True。
        """
        import subprocess
        try:
            if getattr(sys, 'frozen', False):
                exe_dir = os.path.dirname(sys.executable)
                editor_exe = os.path.join(exe_dir, "Sora Editor.exe")
                if not os.path.isfile(editor_exe):
                    QMessageBox.warning(
                        self, "テキストエディタが見つかりません",
                        f"Sora Editor.exe が見つかりません:\n{exe_dir}\n\n"
                        "EXE版を使う場合は両アプリを同じフォルダに置いてください。\n"
                        f"ファイル:\n{local_path}",
                    )
                    return False
                cmd = [editor_exe, local_path]
                cwd = exe_dir
            else:
                editor_script = os.path.join(
                    os.path.dirname(os.path.abspath(__file__)), 'text_editor.py'
                )
                cmd = [sys.executable, editor_script, local_path]
                cwd = os.path.dirname(editor_script)
            if search:
                cmd += ['--search', search]
            if profile_name:
                cmd += ['--profile', profile_name]
            if sql_extract:
                cmd += ['--sql-extract']
            subprocess.Popen(cmd, cwd=cwd)
            return True
        except Exception as e:
            QMessageBox.critical(
                self, "起動エラー",
                f"Sora Editor の起動に失敗しました:\n{e}"
            )
            return False

    def _open_selection_in_sora(self, conn, selected_text: str):
        """ログセルで選択したテキストを一時ファイルに保存 → Sora Editor を
        SQL抽出モードで起動する。"""
        if not selected_text.strip():
            QMessageBox.information(
                self, "選択なし",
                "ログセル内でSQLを含む範囲を選択してから実行してください。"
            )
            return
        import tempfile
        import time as _time
        tmp_dir = os.path.join(tempfile.gettempdir(), 'ssh_log_viewer', '_selection')
        os.makedirs(tmp_dir, exist_ok=True)
        tmp_path = os.path.join(tmp_dir, f"selection_{int(_time.time() * 1000)}.log")
        try:
            with open(tmp_path, 'w', encoding='utf-8') as f:
                f.write(selected_text)
        except Exception as e:
            QMessageBox.critical(self, "保存エラー", str(e))
            return
        profile_name = getattr(conn, '_profile_name', '') or ''
        if self._launch_sora(tmp_path, profile_name=profile_name, sql_extract=True):
            self._status.setText("📝 選択範囲を Sora Editor で SQL抽出 で開きました")

    def _open_settings(self):
        dlg = SettingsDialog(self)
        # 設定移行ボタンを MainWindow のメソッドに接続
        dlg.export_btn.clicked.connect(self._export_settings)
        dlg.import_btn.clicked.connect(self._import_settings)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._apply_all_settings()

    # ---------------------------------------------- アラート調査

    def _open_alert_analysis(self):
        """アラートメール解析ダイアログを開く"""
        dlg = AlertAnalysisDialog(self)
        dlg.investigation_requested.connect(self._start_investigation)
        dlg.show()

    def _start_investigation(self, info: dict):
        """解析結果を元にサーバー接続 → 推定ログを開く → ロットIDでフィルタ"""
        prof_name = info.get('profile_name')
        if not prof_name:
            QMessageBox.warning(self, "選択なし", "プロファイルを選んでください。")
            return
        profiles = _load_profiles()
        prof = profiles.get(prof_name)
        if not prof:
            QMessageBox.warning(self, "プロファイル不明",
                f"「{prof_name}」が見つかりません。")
            return

        self._status.setText(f"🔎 調査中: {prof_name} に接続...")
        QApplication.processEvents()

        # 既に同じプロファイルで接続済みならそれを使う
        panel = None
        for p in self._panels:
            if getattr(p, '_profile_name', None) == prof_name:
                panel = p
                break
        if panel is None:
            try:
                self._connect_from_profile(prof_name, prof)
                panel = self._panels[-1]
            except Exception as e:
                QMessageBox.critical(self, "接続エラー", str(e))
                self._status.setText("⚠ 接続失敗")
                return

        # ログDIR + プロセス名 でファイル候補を組み立て、SFTP/exec で存在確認
        proc = info.get('process', '')

        if not proc:
            QMessageBox.warning(self, "プロセス未抽出",
                "メールからプロセス名が抽出できませんでした。\n"
                "左ツリーから手動でログを選んでください。")
            return

        # 検索候補ディレクトリ (直下のみ・非再帰、優先順):
        #   1. 左ツリー選択 / パス入力欄 / log_dir (= _resolve_search_dir)
        #   2. この接続で既に開いているログセルのフォルダ (ワークスペースで
        #      開いた group02/messvr 等。ログの実在場所が分かる)
        search_dirs: list[str] = []
        primary = self._resolve_search_dir(panel, prof)
        if primary:
            search_dirs.append(primary.rstrip('/') or '/')
        try:
            for v in self.grid.viewers():
                if getattr(v, 'conn', None) is panel.conn:
                    d = '/'.join(v.filepath.rstrip('/').split('/')[:-1]) or '/'
                    if d not in search_dirs:
                        search_dirs.append(d)
        except Exception:
            pass

        self._status.setText(f"🔎 {proc} のログを検索中... ({len(search_dirs)}フォルダ)")
        QApplication.processEvents()

        # 各候補ディレクトリ直下を listdir → プロセス名トークンでマッチ
        # (group02_ctlsvr1 → ctlsvr / ローテーション messvr.log.20260504 も対象)
        found_path = None
        searched_dir = ''                  # 実際にヒット判定したDIR
        stat_map: dict = {}
        matches: list[str] = []
        log_files_in_dir: list[str] = []   # 診断表示用
        for cand in search_dirs:
            try:
                entries = panel.conn.listdir(cand)
            except Exception:
                continue
            filenames = [e.filename for e in entries
                         if not stat_mod.S_ISDIR(e.st_mode)]
            cand_stat = {e.filename: e for e in entries
                         if not stat_mod.S_ISDIR(e.st_mode)}
            cand_logs = [f for f in filenames if '.log' in f.lower()]
            cand_matches = self._find_log_by_proc(filenames, proc)
            if cand_matches:
                matches = cand_matches
                searched_dir = cand
                stat_map = cand_stat
                log_files_in_dir = cand_logs
                break
            # 診断用に最初の候補の状況を保持
            if not searched_dir:
                searched_dir = cand
                log_files_in_dir = cand_logs

        # アラート時刻 (ローテーションログの絞り込みに使う)
        alert_dt = _parse_alert_dt(info.get('timestamp', ''))

        if len(matches) == 1:
            found_path = f"{searched_dir}/{matches[0]}"
        elif len(matches) >= 2:
            # 時刻でアラートを含むログが一意に推定できれば、そのまま開く
            # (5/1〜の大量ローテーションをいちいち選ばせない)
            best = _pick_log_for_alert(matches, alert_dt) if alert_dt else None
            if best:
                found_path = f"{searched_dir}/{best}"
                self._status.setText(
                    f"🕒 アラート時刻 {alert_dt:%Y/%m/%d %H:%M:%S} を含む "
                    f"{best} を自動選択"
                )
            else:
                # 時刻不明 → 従来どおり選択ダイアログ (★で推定ログをマーク)
                dlg = LogSelectionDialog(searched_dir, matches, stat_map, self,
                                         alert_dt=alert_dt)
                if dlg.exec() == QDialog.DialogCode.Accepted:
                    selected = dlg.selected_paths()
                    if selected:
                        if len(selected) >= 2:
                            self._open_multiple_for_alert(panel, selected, info)
                            return
                        found_path = selected[0]

        if not found_path:
            # 何も見つからない → 最初の候補DIRに移動してユーザー選択を促す
            try:
                panel._load(searched_dir or (search_dirs[0] if search_dirs else '/'))
            except Exception:
                pass
            # 診断: 実際に検索したDIRと、そこにあった .log ファイルを提示
            if log_files_in_dir:
                log_list = '\n'.join(f"  ・{f}" for f in log_files_in_dir[:15])
                diag = (
                    f"このフォルダには以下の .log があります:\n{log_list}\n\n"
                    "プロセス名とログ名が対応していない可能性があります。"
                )
            else:
                diag = (
                    "このフォルダ直下には .log ファイルがありません。\n"
                    "ログが別フォルダにある場合は、左ツリーでそのフォルダを\n"
                    "開いてから再実行してください。"
                )
            QMessageBox.information(
                self, "ログ自動特定失敗",
                f"検索したフォルダ ({len(search_dirs)}件):\n  " +
                '\n  '.join(search_dirs) + "\n\n"
                f"抽出プロセス名: 「{proc}」\n"
                f"探したキーワード: {', '.join(self._process_name_tokens(proc))}\n\n"
                f"{diag}\n\n"
                "対処: 左ツリーで対象フォルダ/ログを選択 → 再度「調査開始」、\n"
                "またはツリーから手動でログを開いてください。"
            )
            self._status.setText(
                f"⚠ {proc} のログを自動特定できず → ツリーで対象フォルダを選択してください"
            )
            return

        # ファイル特定 → Sora Editor で直接開く
        # (LogViewer はアラート受信〜サーバー特定までの入口。実調査は Sora Editor で)
        lot = info.get('lot') or ''
        self._open_in_text_editor(panel.conn, found_path, search=lot)

    def _open_multiple_for_alert(self, panel, paths: list[str], info: dict):
        """選択された複数ログを Sora Editor で開く (各タブ + 検索)"""
        lot = info.get('lot') or ''
        for path in paths:
            self._open_in_text_editor(panel.conn, path, search=lot)
        self._status.setText(
            f"📝 Sora Editor で {len(paths)} 件のログを開きました / lot={lot or '-'}"
        )

    @staticmethod
    def _process_name_tokens(proc: str) -> list[str]:
        """プロセス名から検索キーワードを派生 (長い順、重複除去)。
        例: 'group02_ctlsvr1'
             → ['group02_ctlsvr1', 'group02', 'ctlsvr1', 'ctlsvr']
        """
        keywords: list[str] = []
        if not proc:
            return keywords
        keywords.append(proc)
        for tok in proc.split('_'):
            if not tok:
                continue
            keywords.append(tok)
            # 末尾の数字 (インスタンス番号) を取り除いた形
            stripped = re.sub(r'\d+$', '', tok)
            if stripped and stripped != tok:
                keywords.append(stripped)
        # 重複除去・長い順
        seen = set()
        result = []
        for k in sorted(keywords, key=len, reverse=True):
            kl = k.lower()
            if kl not in seen:
                seen.add(kl)
                result.append(k)
        return result

    @staticmethod
    def _find_log_by_proc(filenames: list[str], proc: str) -> list[str]:
        """ディレクトリ内のファイル一覧からプロセス名にマッチするログを推定。
        対象は『.log を含むファイル』全般:
          - foo.log                  (current log)
          - foo.log.20250520         (rotation by date)
          - foo.log.20250520165601   (rotation w/ time)
          - foo.log.1 / foo.log.2    (logrotate numeric)
          - foo.log-20250520         (dash variant)
          - foo.log_old / foo.log.bak  等
        日付サフィックスだけ (foo.20250714) や バリアント (foo_sun) は除外。
        優先度順でリスト返却。
        """
        keywords = MainWindow._process_name_tokens(proc)
        results: list[str] = []
        seen: set[str] = set()

        def add(fn: str):
            if fn not in seen:
                seen.add(fn)
                results.append(fn)

        # まず ".log を含む" ファイルだけに限定 (.gz除外)
        log_files = [
            f for f in filenames
            if ('.log' in f.lower()) and not f.lower().endswith('.gz')
        ]

        for kw in keywords:
            kwl = kw.lower()
            # 1. 完全一致 "{kw}.log" を最優先
            target = f'{kw}.log'.lower()
            for f in log_files:
                if f.lower() == target:
                    add(f)
            # 2. ".log" で終わる current log (kw 部分一致)
            for f in log_files:
                if f.lower().endswith('.log') and kwl in f.lower():
                    add(f)
            # 3. ローテーション系: .log + 後ろに何か (.log.YYYYMMDD, .log.1, .log-old, .log_bak 等)
            for f in log_files:
                if kwl in f.lower() and not f.lower().endswith('.log'):
                    add(f)
            if results:
                # 最初のキーワードでヒットしたら他のトークンは試さない
                break
        return results

    def _resolve_search_dir(self, panel, prof: dict) -> str:
        """検索ベース DIR を決定:
        1. 左ツリーで選択中の項目 (フォルダ or ファイルの親) を最優先
        2. パス入力欄に表示中のパス
        3. プロファイルの log_dir
        4. /var/log (最終フォールバック)
        """
        # 1. ツリー選択
        try:
            sel = panel.tree.selectedItems()
            if sel:
                d = sel[0].data(0, Qt.ItemDataRole.UserRole)
                if isinstance(d, dict):
                    if d.get('is_dir'):
                        return d.get('path').rstrip('/') or '/'
                    # ファイル選択なら親ディレクトリ
                    p = d.get('path', '')
                    if p:
                        parent = '/'.join(p.rstrip('/').split('/')[:-1]) or '/'
                        return parent
        except Exception:
            pass
        # 2. 入力欄の現在パス
        try:
            cur = panel.path_input.text().strip()
            if cur:
                return cur.rstrip('/') or '/'
        except Exception:
            pass
        # 3. プロファイル
        log_dir = prof.get('log_dir', '/var/log').rstrip('/') or '/var/log'
        return log_dir

    def _remote_file_exists(self, conn, path: str) -> bool:
        """リモートに指定パスのファイルがあるか確認"""
        # SSHConnection は SFTP を持つので stat で確認
        try:
            if hasattr(conn, 'sftp') and conn.sftp is not None:
                conn.sftp.stat(path)
                return True
        except Exception:
            return False
        # Telnet 等 SFTP がない場合: test -f コマンドで判定
        try:
            out = conn.exec(f'test -f "{path}" && echo OK_EXISTS || echo NO').strip()
            return 'OK_EXISTS' in out
        except Exception:
            return False

    # ---------------------------------------------- 設定移行 (Export / Import)

    _MIGRATION_APP_KEY = "Multi-Server Log Viewer"
    _MIGRATION_SCHEMA = 1

    def _export_settings(self):
        """プロファイル + ワークスペース + UI設定をJSONファイルにエクスポート"""
        from datetime import datetime
        path, _ = QFileDialog.getSaveFileName(
            self, "設定をエクスポート",
            f"mslv_settings_{datetime.now():%Y%m%d_%H%M%S}.json",
            "JSON (*.json);;すべて (*)",
        )
        if not path:
            return
        bundle = {
            "schema_version": self._MIGRATION_SCHEMA,
            "app": self._MIGRATION_APP_KEY,
            "version": __version__,
            "exported_at": datetime.now().isoformat(timespec='seconds'),
            "profiles":   _load_profiles(),
            "workspaces": _load_workspaces(),
            "settings":   dict(SETTINGS),
        }
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(bundle, f, ensure_ascii=False, indent=2)
            self._status.setText(
                f"📤 エクスポート完了: {len(bundle['profiles'])}プロファイル / "
                f"{len(bundle['workspaces'])}ワークスペース → {os.path.basename(path)}"
            )
        except Exception as e:
            QMessageBox.critical(self, "エクスポートエラー", str(e))

    def _import_settings(self):
        """JSONファイルからプロファイル/ワークスペース/UI設定をインポート"""
        path, _ = QFileDialog.getOpenFileName(
            self, "設定をインポート", "", "JSON (*.json);;すべて (*)"
        )
        if not path:
            return
        try:
            with open(path, 'r', encoding='utf-8') as f:
                bundle = json.load(f)
        except Exception as e:
            QMessageBox.critical(self, "読込エラー", str(e))
            return
        if bundle.get('app') != self._MIGRATION_APP_KEY:
            QMessageBox.warning(
                self, "アプリ違い",
                f"このファイルは別アプリのエクスポートです: {bundle.get('app')}",
            )
            return

        profiles   = bundle.get('profiles', {})
        workspaces = bundle.get('workspaces', {})
        settings   = bundle.get('settings', {})

        # 現在の状況を確認
        cur_profiles = _load_profiles()
        cur_ws       = _load_workspaces()
        msg = (
            f"インポートします:\n"
            f"・プロファイル: {len(profiles)}件 "
            f"(現在 {len(cur_profiles)}件)\n"
            f"・ワークスペース: {len(workspaces)}件 "
            f"(現在 {len(cur_ws)}件)\n"
            f"・UI設定: {len(settings)}項目\n\n"
            "どう取り込みますか？\n"
            "「Yes」… マージ (重複は新しい方で上書き、既存も残す)\n"
            "「No」 … 置換 (現在の設定を消して全部入れ替え)\n"
            "「Cancel」… 中止"
        )
        ans = QMessageBox.question(
            self, "インポート", msg,
            QMessageBox.StandardButton.Yes |
            QMessageBox.StandardButton.No |
            QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Yes,
        )
        if ans == QMessageBox.StandardButton.Cancel:
            return

        if ans == QMessageBox.StandardButton.Yes:
            # マージ
            new_profiles = {**cur_profiles, **profiles}
            new_ws       = {**cur_ws, **workspaces}
        else:
            # 置換
            new_profiles = dict(profiles)
            new_ws       = dict(workspaces)

        try:
            _save_profiles(new_profiles)
            _save_workspaces(new_ws)
            # UI 設定はマージ後保存
            for k, v in settings.items():
                if k in _DEFAULT_SETTINGS:
                    SETTINGS[k] = v
            _save_settings(SETTINGS)
        except Exception as e:
            QMessageBox.critical(self, "保存エラー", str(e))
            return

        self._refresh_workspace_combo()
        self._apply_all_settings()
        self._status.setText(
            f"📥 インポート完了: プロファイル {len(new_profiles)}件 / "
            f"ワークスペース {len(new_ws)}件"
        )

    def _apply_all_settings(self):
        """SETTINGS の変更を全 UI に反映する。
        途中で1つ例外が出ても残りが必ず実行されるよう各処理を try で隔離する
        (例外で止まるとツールバーだけ更新されグリッドが古いまま、になり得るため)。
        """
        try:
            self._apply_theme()
        except Exception:
            pass
        for panel in self._panels:
            try:
                panel.apply_settings()
            except Exception:
                pass
        # 空セルとビューアの両方を更新
        try:
            self.grid.apply_settings()
        except Exception:
            pass
        for dlg in list(self._terminals):
            try:
                dlg.apply_settings()
            except Exception:
                pass
        # スタイルシートを再設定しても子ウィジェットが再描画されないことがあるため、
        # 全ウィジェットを強制的に再ポリッシュしてライブ反映を確実にする。
        try:
            self._force_restyle()
        except Exception:
            pass

    def _force_restyle(self):
        """ウィジェットツリー全体のスタイルを再適用して即時再描画させる。"""
        from PyQt6.QtWidgets import QWidget as _QW
        widgets = self.findChildren(_QW)
        widgets.append(self)
        for w in widgets:
            try:
                st = w.style()
                st.unpolish(w)
                st.polish(w)
                w.update()
            except Exception:
                pass

    # ---------------------------------------------------------------- 終了処理

    def closeEvent(self, event):
        """アプリ終了時に Tail スレッドを止め、SSH/Telnet 接続をきちんと切断する。
        これをしないと remote 側の `tail -F` プロセスや SSH セッションが
        サーバー側にしばらく残ってしまう (タイムアウトまで)。
        """
        # 1. 全ログセルの tail を停止 (各 worker は finally で channel.close())
        try:
            for v in self.grid.viewers():
                v.stop_tail()
        except Exception:
            pass

        # 2. 全ターミナルダイアログ + ポップアップログを閉じる
        for dlg in list(self._terminals):
            try:
                dlg.close()
            except Exception:
                pass
        self._terminals.clear()
        for pop in list(self._log_popups):
            try:
                pop.close()
            except Exception:
                pass
        self._log_popups.clear()

        # 3. 全サーバー接続を明示的に切断 (SSHClient.close / Telnet socket close)
        for panel in list(self._panels):
            try:
                panel.conn.disconnect()
            except Exception:
                pass

        super().closeEvent(event)

    def _save_log_dir(self, panel: ServerPanel, path: str):
        name = getattr(panel, '_profile_name', '-- 新規 --')
        if name == '-- 新規 --':
            QMessageBox.information(
                self, "保存できません",
                "接続時にプロファイルを選択または保存してください。\n"
                "接続ダイアログで「保存」ボタンを押してプロファイルを作成すると記憶できます。"
            )
            return
        profiles = _load_profiles()
        if name not in profiles:
            QMessageBox.warning(self, "警告", f"プロファイル「{name}」が見つかりません。")
            return
        dir_value = path.strip()
        # 初期DIR = log_dir のみを保存 (last_dir 自動復元は廃止したため書かない)
        profiles[name]['log_dir'] = dir_value
        _save_profiles(profiles)
        # パネル側の path_input も保存値に合わせておく
        try:
            panel.path_input.setText(dir_value)
        except Exception:
            pass
        self._status.setText(f"📌 初期DIRに保存しました: [{name}] = {dir_value}")

    # ---------------------------------------------------------------- グリッド

    def _on_grid_change(self, text: str):
        if text in _GRID_PRESETS:
            r, c = _GRID_PRESETS[text]
            self.grid.set_size(r, c)

    def _open_log(self, conn: SSHConnection, path: str, color_idx: int):
        # プロファイル名があれば優先、なければ user@host
        label = conn.label
        for p in self._panels:
            if p.conn is conn:
                name = getattr(p, '_profile_name', None)
                if name and name != '-- 新規 --':
                    label = name
                break
        viewer = MiniLogViewer(conn, path, label, color_idx)
        viewer.editor_requested.connect(self._open_in_text_editor)
        viewer.sql_selection_requested.connect(self._open_selection_in_sora)
        if not self.grid.assign(viewer):
            QMessageBox.information(
                self, "グリッド満杯",
                "空きセルがありません。グリッドサイズを大きくするか、✕でセルを閉じてください。"
            )
            viewer.deleteLater()
        else:
            self._status.setText(f"開いた: {os.path.basename(path)}  ({conn.label})")

    def _apply_global_filter(self):
        self.grid.apply_filter(
            self.global_filter.text(),
            self.global_level.currentText(),
        )

    # ---------------------------------------------------------------- テーマ

    def _apply_theme(self):
        t = _theme()
        fs_tb = SETTINGS.get('toolbar_font_size', 11)
        self.setStyleSheet(f"""
            QMainWindow,QWidget {{ background:{t['bg']}; color:{t['text']}; }}
            QToolTip {{ background-color:#2b2b2b; color:#ffffff;
                        border:1px solid #666; padding:3px 6px; }}
            QToolBar  {{ background:{t['toolbar_bg']}; border:none; padding:2px 4px; spacing:3px; }}
            QToolBar QLabel {{ color:{t['text_dim']}; font-size:{max(fs_tb-1, 7)}px; }}
            QToolBar QPushButton {{ background:{t['control_bg']};color:{t['text']};border:none;
                                    padding:2px 8px;border-radius:2px;font-size:{fs_tb}px; }}
            QToolBar QPushButton:hover   {{ background:{t['control_hover']}; }}
            QToolBar QPushButton:checked {{ background:{t['selection']}; }}
            QToolBar QComboBox {{ background:{t['control_bg']};color:{t['text']};
                                  border:1px solid {t['border']};
                                  padding:1px 3px;font-size:{fs_tb}px; }}
            QToolBar QLineEdit {{ background:{t['panel_bg']};color:{t['text']};
                                  border:1px solid {t['border']};
                                  padding:1px 3px;font-size:{fs_tb}px; }}
            QComboBox {{ background:{t['control_bg']};color:{t['text']};
                         border:1px solid {t['border']};padding:1px 3px; }}
            QComboBox::drop-down {{ border:none; width:14px; }}
            QComboBox QAbstractItemView {{ background:{t['panel_bg']};color:{t['text']};
                                           selection-background-color:{t['selection']}; }}
            QLineEdit {{ background:{t['panel_bg']};color:{t['text']};
                         border:1px solid {t['border']};padding:1px 3px; }}
            QStatusBar {{ background:{t['toolbar_bg']};color:{t['text_dim']}; }}
            QSplitter::handle {{ background:{t['border']}; }}
            QSplitter::handle:horizontal {{ width:2px; }}
            QSplitter::handle:vertical   {{ height:3px; }}
            QScrollBar:vertical {{
                background:{t['panel_bg']}; width:12px; border:none; margin:0;
            }}
            QScrollBar::handle:vertical {{
                background:{t['control_bg']}; border-radius:4px;
                min-height:30px; margin:2px;
            }}
            QScrollBar::handle:vertical:hover {{ background:{t['control_hover']}; }}
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {{ height:0; width:0; }}
            QScrollBar::add-page:vertical,
            QScrollBar::sub-page:vertical {{ background:none; }}
            QScrollBar:horizontal {{
                background:{t['panel_bg']}; height:12px; border:none; margin:0;
            }}
            QScrollBar::handle:horizontal {{
                background:{t['control_bg']}; border-radius:4px;
                min-width:30px; margin:2px;
            }}
            QScrollBar::handle:horizontal:hover {{ background:{t['control_hover']}; }}
            QScrollBar::add-line:horizontal,
            QScrollBar::sub-line:horizontal {{ height:0; width:0; }}
            QScrollBar::add-page:horizontal,
            QScrollBar::sub-page:horizontal {{ background:none; }}
        """)
        # ツールバー自前スタイル (メインwindowのQToolBarルールを上書きしているため、
        # ライブのテーマ変更ではここで明示的に再適用しないと更新されない)
        self._apply_toolbar_style()
        # 「サーバー未接続」のラベル色も合わせる
        if hasattr(self, '_no_server_label') and self._no_server_label is not None:
            self._no_server_label.setStyleSheet(
                f"color:{t['text_dim']}; padding:12px; font-size:11px;"
            )
        # ツールバーの右寄せスペーサー (生成時固定色) もライブ更新
        if hasattr(self, '_tb_spacer') and self._tb_spacer is not None:
            self._tb_spacer.setStyleSheet(f"background:{t['toolbar_bg']};")


# ---------------------------------------------------------------------------
# エントリーポイント
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    # 起動時の一時ファイルクリーンアップ (「テキストエディタで開く」DL分)
    import tempfile as _tempfile
    try:
        _tmp_root = os.path.join(_tempfile.gettempdir(), 'ssh_log_viewer')
        _cleanup_old_temp_files(_tmp_root)
    except Exception:
        pass

    app = QApplication(sys.argv)
    app.setApplicationName("Multi-Server Log Viewer")
    try:
        from app_icons import ssh_log_viewer_icon
        app.setWindowIcon(ssh_log_viewer_icon())
    except Exception:
        pass
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
