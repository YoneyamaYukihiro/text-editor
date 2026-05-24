#!/usr/bin/env python3
"""SSH Log Viewer — マルチサーバー・グリッドログ解析ツール"""
import sys, os, re, json, stat as stat_mod, time

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
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize, QTimer
from PyQt6.QtGui import (
    QFont, QColor, QTextCharFormat, QSyntaxHighlighter,
    QAction, QKeySequence,
)


# ---------------------------------------------------------------------------
# サーバーカラーパレット（最大6サーバー）
# ---------------------------------------------------------------------------

_PALETTES = [
    ('#0D2137', '#4A9EFF'),   # blue
    ('#0D2A0D', '#5FBF5F'),   # green
    ('#2D1800', '#E8A030'),   # orange
    ('#1A0D2A', '#9876CC'),   # purple
    ('#2A0D0D', '#CF6679'),   # red
    ('#1A2A2A', '#4EC9B0'),   # teal
]

def _palette(idx: int) -> tuple[str, str]:
    return _PALETTES[idx % len(_PALETTES)]


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
# SSH接続クラス
# ---------------------------------------------------------------------------

class SSHConnection:
    def __init__(self):
        self.client = None
        self.sftp   = None
        self.label  = ''

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
        self.sftp   = c.open_sftp()
        self.label  = f"{user}@{host}"

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

    def listdir(self, path: str):
        entries = self.sftp.listdir_attr(path)
        entries.sort(key=lambda a: (not stat_mod.S_ISDIR(a.st_mode), a.filename.lower()))
        return entries

    def read_tail(self, path: str, lines: int = 5000) -> str:
        _, out, _ = self.client.exec_command(
            f'tail -n {lines} "{path}" 2>/dev/null || cat "{path}" 2>/dev/null'
        )
        return out.read().decode('utf-8', errors='replace')

    def exec(self, cmd: str) -> str:
        _, out, _ = self.client.exec_command(cmd)
        return out.read().decode('utf-8', errors='replace')


# ---------------------------------------------------------------------------
# Tail -f ワーカー
# ---------------------------------------------------------------------------

class TailWorker(QThread):
    new_text = pyqtSignal(str)
    error    = pyqtSignal(str)

    def __init__(self, conn: SSHConnection, path: str):
        super().__init__()
        self._conn = conn
        self._path = path
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            transport = self._conn.client.get_transport()
            chan = transport.open_session()
            chan.exec_command(f'tail -f "{self._path}"')
            buf = b''
            while not self._stop:
                if chan.recv_ready():
                    buf += chan.recv(4096)
                    parts = buf.split(b'\n')
                    buf   = parts[-1]
                    text  = b'\n'.join(parts[:-1]).decode('utf-8', errors='replace')
                    if text:
                        self.new_text.emit(text)
                else:
                    time.sleep(0.1)
            chan.close()
        except Exception as e:
            self.error.emit(str(e))


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
    _LEVELS = [
        (re.compile(r'\b(?:ERROR|CRITICAL|FATAL|SEVERE)\b', re.I), '#3D1515', '#FF7070'),
        (re.compile(r'\bWARN(?:ING)?\b', re.I),                    '#2D2512', '#E8B26A'),
        (re.compile(r'\bINFO\b', re.I),                             '#1A2A1A', '#6A9F6A'),
        (re.compile(r'\bDEBUG\b', re.I),                            None,      '#707070'),
        (re.compile(r'\bTRACE\b', re.I),                            None,      '#505050'),
    ]
    _INLINE = [
        (re.compile(r'\d{4}[-/]\d{2}[-/]\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:\d{2})?'), '#4EC9B0'),
        (re.compile(r'\b\d{2}:\d{2}:\d{2}(?:[.,]\d+)?\b'),  '#4EC9B0'),
        (re.compile(r'\[[\w\s.:\-/]+\]'),                    '#9876AA'),
        (re.compile(r'\b\w+(?:Exception|Error)\b'),           '#FF7070'),
        (re.compile(r'^\s+at\s+[\w.$<>()\[\]/]+'),           '#CC7832'),
        (re.compile(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b'), '#4EC9B0'),
        (re.compile(r'\b[45]\d{2}\b'),                        '#FF7070'),
    ]

    def highlightBlock(self, text: str):
        for pat, bg, fg in self._LEVELS:
            if pat.search(text):
                fmt = QTextCharFormat()
                if bg: fmt.setBackground(QColor(bg))
                fmt.setForeground(QColor(fg))
                self.setFormat(0, len(text), fmt)
                break
        for pat, color in self._INLINE:
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(color))
            for m in pat.finditer(text):
                self.setFormat(m.start(), m.end() - m.start(), fmt)


# ---------------------------------------------------------------------------
# ミニログビューア（グリッド1セル分）
# ---------------------------------------------------------------------------

class MiniLogViewer(QWidget):
    tail_changed    = pyqtSignal(bool)
    close_requested = pyqtSignal(object)

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
        header.setFixedHeight(22)
        header.setStyleSheet(f"background:{self._bg};")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(5, 0, 2, 0)
        hl.setSpacing(4)

        dot = QLabel("●")
        dot.setStyleSheet(f"color:{self._fg}; font-size:9px;")
        dot.setFixedWidth(10)
        hl.addWidget(dot)

        lbl = QLabel(f"{self.server_label}  ·  {os.path.basename(self.filepath)}")
        lbl.setStyleSheet(f"color:{self._fg}; font-size:10px; font-weight:600;")
        lbl.setToolTip(self.filepath)
        hl.addWidget(lbl, 1)

        for text, tip, slot, check in [
            ("⏩", "Tail -f", None, True),
            ("↺",  "再読み込み", self._load, False),
            ("✕",  "閉じる", lambda: self.close_requested.emit(self), False),
        ]:
            btn = QPushButton(text)
            btn.setFixedSize(20, 18)
            btn.setToolTip(tip)
            btn.setStyleSheet(
                "QPushButton{background:#00000040;color:#ccc;border:none;font-size:10px;}"
                "QPushButton:hover{background:#00000080;}"
                "QPushButton:checked{background:#214283;}"
            )
            if check:
                btn.setCheckable(True)
                self.tail_btn = btn
                btn.toggled.connect(self._toggle_tail)
            else:
                btn.clicked.connect(slot)
            hl.addWidget(btn)
        root.addWidget(header)

        # ── フィルタバー（超コンパクト） ─────────────────────────────
        fbar = QWidget()
        fbar.setFixedHeight(20)
        fbar.setStyleSheet("background:#252525;")
        fl = QHBoxLayout(fbar)
        fl.setContentsMargins(4, 1, 4, 1)
        fl.setSpacing(3)

        self.filter_input = QLineEdit()
        self.filter_input.setPlaceholderText("フィルタ...")
        self.filter_input.setStyleSheet(
            "background:#333;color:#a9b7c6;border:none;padding:0 2px;font-size:10px;"
        )
        self.filter_input.textChanged.connect(self._apply_filter)
        fl.addWidget(self.filter_input, 1)

        self.level_combo = QComboBox()
        self.level_combo.addItems(["ALL", "ERR+", "WRN+", "INF+"])
        self.level_combo.setFixedWidth(52)
        self.level_combo.setStyleSheet(
            "background:#333;color:#a9b7c6;border:none;font-size:10px;"
            "QComboBox::drop-down{border:none;width:12px;}"
        )
        self.level_combo.currentIndexChanged.connect(self._apply_filter)
        fl.addWidget(self.level_combo)
        root.addWidget(fbar)

        # ── テキストエリア ────────────────────────────────────────────
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setFont(QFont("Consolas", 9))
        self.text.setStyleSheet(
            "background:#1a1a1a;color:#a9b7c6;border:none;"
            "selection-background-color:#214283;"
        )
        self.highlighter = LogHighlighter(self.text.document())
        root.addWidget(self.text, 1)

        # ── ステータス（超コンパクト） ────────────────────────────────
        self.stats = QLabel("")
        self.stats.setFixedHeight(14)
        self.stats.setStyleSheet(
            "background:#222;color:#555;padding:0 4px;font-size:9px;"
        )
        root.addWidget(self.stats)

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
        self.tail_changed.emit(on)

    def _append(self, text: str):
        self._all_lines.extend(text.splitlines())
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
        self.setStyleSheet("background:#141414; border:1px solid #242424;")
        lbl = QLabel("空き\nファイルをダブルクリックで開く")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet("color:#303030; font-size:11px; border:none;")
        lay = QVBoxLayout(self)
        lay.addWidget(lbl)


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
            extra.deleteLater()
        self._slots = self._slots[:n]

        # 既存スプリッターを除去
        if self._hsplit:
            for slot in self._slots:
                slot.setParent(None)
            self._outer.removeWidget(self._hsplit)
            self._hsplit.deleteLater()

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
                vsplit.setStretchFactor(row, 1)
            hsplit.addWidget(vsplit)
            hsplit.setStretchFactor(col, 1)
            self._vsplits.append(vsplit)

        self._hsplit = hsplit
        self._outer.addWidget(hsplit)

        # レイアウト確定後に均等分割を強制適用
        QTimer.singleShot(0, self._equalize)

    def _equalize(self):
        """全スプリッターを均等分割する"""
        if not self._hsplit:
            return
        w = self._hsplit.width()
        h = self._hsplit.height()
        if w > 0 and self._cols > 0:
            self._hsplit.setSizes([w // self._cols] * self._cols)
        for vsplit in self._vsplits:
            if h > 0 and self._rows > 0:
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


# ---------------------------------------------------------------------------
# リモートファイルブラウザ（1サーバー分）
# ---------------------------------------------------------------------------

class ServerPanel(QWidget):
    """1サーバーの接続状態＋ファイルツリー"""
    file_open_requested  = pyqtSignal(object, str, int)   # conn, path, color_idx
    disconnect_requested = pyqtSignal(object)             # self
    save_dir_requested   = pyqtSignal(object, str)        # self, path

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

        # サーバーヘッダー
        header = QWidget()
        header.setFixedHeight(24)
        header.setStyleSheet(f"background:{self._bg};")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(6, 0, 4, 0)
        hl.setSpacing(4)
        dot = QLabel("●")
        dot.setStyleSheet(f"color:{self._fg}; font-size:10px;")
        hl.addWidget(dot)
        lbl = QLabel(self.conn.label)
        lbl.setStyleSheet(f"color:{self._fg}; font-size:11px; font-weight:600;")
        hl.addWidget(lbl, 1)
        disc = QPushButton("切断")
        disc.setFixedHeight(18)
        disc.setStyleSheet(
            "QPushButton{background:#00000050;color:#aaa;border:none;padding:0 6px;font-size:10px;}"
            "QPushButton:hover{background:#00000090;}"
        )
        disc.clicked.connect(lambda: self.disconnect_requested.emit(self))
        hl.addWidget(disc)
        layout.addWidget(header)

        # パスバー
        path_row = QHBoxLayout()
        path_row.setContentsMargins(2, 1, 2, 1)
        path_row.setSpacing(2)
        self.path_input = QLineEdit(self._initial_path)
        self.path_input.setStyleSheet(
            "background:#222;color:#a9b7c6;border:none;padding:1px 3px;font-size:10px;"
        )
        self.path_input.returnPressed.connect(lambda: self._load(self.path_input.text()))
        go_btn = QPushButton("→")
        go_btn.setFixedSize(20, 18)
        go_btn.setStyleSheet("background:#333;color:#aaa;border:none;")
        go_btn.clicked.connect(lambda: self._load(self.path_input.text()))
        save_btn = QPushButton("📌")
        save_btn.setFixedSize(22, 18)
        save_btn.setToolTip("現在のDIRをプロファイルに保存")
        save_btn.setStyleSheet("background:#333;color:#aaa;border:none;font-size:11px;")
        save_btn.clicked.connect(
            lambda: self.save_dir_requested.emit(self, self.path_input.text())
        )
        path_row.addWidget(self.path_input, 1)
        path_row.addWidget(go_btn)
        path_row.addWidget(save_btn)
        layout.addLayout(path_row)

        # クイックアクセス
        quick = QHBoxLayout()
        quick.setContentsMargins(2, 0, 2, 0)
        quick.setSpacing(2)
        for label, path in [("/var/log", "/var/log"), ("~", "~"), ("/tmp", "/tmp")]:
            btn = QPushButton(label)
            btn.setFixedHeight(16)
            btn.setStyleSheet(
                "background:#2a2a2a;color:#888;border:none;padding:0 3px;font-size:9px;"
            )
            btn.clicked.connect(lambda _, p=path: self._load(p))
            quick.addWidget(btn)
        quick.addStretch()
        layout.addLayout(quick)

        # ファイルツリー
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setStyleSheet(
            "QTreeWidget{background:#1e1e1e;color:#a9b7c6;border:none;font-size:10px;}"
            "QTreeWidget::item{padding:1px 0;}"
            "QTreeWidget::item:selected{background:#214283;}"
            "QTreeWidget::item:hover{background:#2a2a2a;}"
        )
        self.tree.itemDoubleClicked.connect(self._on_double_click)
        self.tree.itemExpanded.connect(self._on_expand)
        layout.addWidget(self.tree, 1)

    def _load(self, path: str):
        if path.strip() == '~':
            path = self.conn.exec('echo $HOME').strip()
        self.path_input.setText(path)
        self.tree.clear()
        self._fill(self.tree.invisibleRootItem(), path)

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

    def _on_double_click(self, item, _col):
        d = item.data(0, Qt.ItemDataRole.UserRole)
        if d and not d['is_dir']:
            self.file_open_requested.emit(self.conn, d['path'], self.color_idx)


# ---------------------------------------------------------------------------
# SSH接続ダイアログ
# ---------------------------------------------------------------------------

class SSHConnectDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("SSH接続")
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
        for text, slot in [("保存", self._save), ("削除", self._delete)]:
            btn = QPushButton(text)
            btn.setFixedWidth(40)
            btn.clicked.connect(slot)
            pr.addWidget(btn)
        lay.addLayout(pr)

        g = QGridLayout()
        g.setSpacing(4)
        fields = [
            ("ホスト:",      "host",     "",                      False),
            ("ポート:",      "port",     "22",                    False),
            ("ユーザー:",    "user",     "",                      False),
            ("パスワード:",  "password", "",                      True),
            ("秘密鍵:",     "key_path", "~/.ssh/id_rsa (省略可)", False),
            ("ログDIR:",    "log_dir",  "/var/log",               False),
        ]
        self._fields: dict[str, QLineEdit] = {}
        for r, (label, key, ph, pw) in enumerate(fields):
            g.addWidget(QLabel(label), r, 0)
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
            else:
                g.addWidget(le, r, 1)
        lay.addLayout(g)

        btns = QHBoxLayout()
        ok = QPushButton("接続")
        ok.clicked.connect(self.accept)
        cancel = QPushButton("キャンセル")
        cancel.clicked.connect(self.reject)
        btns.addWidget(ok)
        btns.addWidget(cancel)
        lay.addLayout(btns)

        self.setStyleSheet("""
            QDialog{background:#2b2b2b;}
            QLabel{color:#a9b7c6;}
            QLineEdit{background:#3a3a3a;color:#a9b7c6;border:1px solid #555;padding:1px 3px;}
            QPushButton{background:#4a4a4a;color:#a9b7c6;border:none;padding:2px 8px;border-radius:2px;}
            QPushButton:hover{background:#5a5a5a;}
            QComboBox{background:#3a3a3a;color:#a9b7c6;border:1px solid #555;padding:1px 3px;}
            QComboBox::drop-down{border:none;width:14px;}
            QComboBox QAbstractItemView{background:#2b2b2b;color:#a9b7c6;selection-background-color:#214283;}
        """)

    def _on_select(self, idx):
        if idx == 0: return
        p = self._profiles.get(self.combo.currentText(), {})
        for k, le in self._fields.items():
            le.setText(str(p.get(k, '')))

    def _save(self):
        name, ok = QInputDialog.getText(self, "保存", "プロファイル名:")
        if not ok or not name.strip(): return
        name = name.strip()
        self._profiles[name] = self._info()
        _save_profiles(self._profiles)
        if self.combo.findText(name) < 0:
            self.combo.addItem(name)
        self.combo.setCurrentText(name)

    def _delete(self):
        name = self.combo.currentText()
        if name == "-- 新規 --": return
        self._profiles.pop(name, None)
        _save_profiles(self._profiles)
        self.combo.removeItem(self.combo.currentIndex())

    def _browse_key(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "秘密鍵", os.path.expanduser("~/.ssh")
        )
        if path: self._fields['key_path'].setText(path)

    def _info(self) -> dict:
        return {k: le.text() for k, le in self._fields.items()}

    def get_info(self) -> dict:
        info = self._info()
        info['port'] = int(info.get('port') or 22)
        return info


# ---------------------------------------------------------------------------
# メインウィンドウ
# ---------------------------------------------------------------------------

_GRID_PRESETS = {
    "1×1": (1, 1), "1×2": (1, 2), "2×1": (2, 1),
    "2×2": (2, 2), "2×4": (2, 4), "3×4": (3, 4),
    "4×3": (4, 3), "4×4": (4, 4),
}


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SSH Log Viewer")
        self.resize(1600, 900)
        self._panels: list[ServerPanel] = []
        self._setup_ui()
        self._apply_theme()

    # ------------------------------------------------------------------ UI

    def _setup_ui(self):
        # ── ツールバー ────────────────────────────────────────────────
        tb = QToolBar("ツールバー")
        tb.setMovable(False)
        tb.setIconSize(QSize(16, 16))
        self.addToolBar(tb)

        tb.addWidget(QLabel(" グリッド: "))
        self.grid_combo = QComboBox()
        self.grid_combo.addItems(_GRID_PRESETS.keys())
        self.grid_combo.setCurrentText("2×2")
        self.grid_combo.setFixedWidth(70)
        self.grid_combo.currentTextChanged.connect(self._on_grid_change)
        tb.addWidget(self.grid_combo)

        tb.addSeparator()

        btn_all_tail = QPushButton("⏩ 全Tail")
        btn_all_tail.clicked.connect(lambda: self.grid.start_all_tail())
        tb.addWidget(btn_all_tail)

        btn_stop_all = QPushButton("⏹ 全停止")
        btn_stop_all.clicked.connect(lambda: self.grid.stop_all_tail())
        tb.addWidget(btn_stop_all)

        tb.addSeparator()

        tb.addWidget(QLabel(" 共通フィルタ: "))
        self.global_filter = QLineEdit()
        self.global_filter.setPlaceholderText("全セルに適用...")
        self.global_filter.setFixedWidth(180)
        tb.addWidget(self.global_filter)

        self.global_level = QComboBox()
        self.global_level.addItems(["ALL", "ERROR+", "WARN+", "INFO+"])
        self.global_level.setFixedWidth(70)
        tb.addWidget(self.global_level)

        apply_btn = QPushButton("適用")
        apply_btn.setFixedWidth(44)
        apply_btn.clicked.connect(self._apply_global_filter)
        tb.addWidget(apply_btn)

        tb.addSeparator()

        add_server_btn = QPushButton("＋ サーバー接続")
        add_server_btn.clicked.connect(self._add_server)
        tb.addWidget(add_server_btn)

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
        conn = SSHConnection()
        self._status.setText(f"接続中: {info['host']}...")
        QApplication.processEvents()
        try:
            conn.connect(info['host'], info['port'], info['user'],
                         info['password'], info['key_path'])
            color_idx  = len(self._panels)
            log_dir    = info.get('log_dir', '/var/log') or '/var/log'
            panel = ServerPanel(conn, color_idx, log_dir, self)
            panel.file_open_requested.connect(self._open_log)
            panel.disconnect_requested.connect(self._remove_server)
            panel.save_dir_requested.connect(self._save_log_dir)
            # プロファイル名を panel に記憶させてDIR更新時に使う
            panel._profile_name = dlg.combo.currentText()
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
        panel.conn.disconnect()
        self._panels.remove(panel)
        panel.deleteLater()
        self._status.setText(f"切断  残 {len(self._panels)} 台")

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
        profiles[name]['log_dir'] = path.strip()
        _save_profiles(profiles)
        self._status.setText(f"📌 保存: [{name}] ログDIR = {path}")

    # ---------------------------------------------------------------- グリッド

    def _on_grid_change(self, text: str):
        if text in _GRID_PRESETS:
            r, c = _GRID_PRESETS[text]
            self.grid.set_size(r, c)

    def _open_log(self, conn: SSHConnection, path: str, color_idx: int):
        server_label = conn.label.split('@')[1] if '@' in conn.label else conn.label
        viewer = MiniLogViewer(conn, path, server_label, color_idx)
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
        self.setStyleSheet("""
            QMainWindow,QWidget { background:#1a1a1a; color:#a9b7c6; }
            QToolBar  { background:#252525; border:none; padding:2px 4px; spacing:3px; }
            QToolBar QLabel { color:#888; font-size:10px; }
            QPushButton { background:#3a3a3a;color:#a9b7c6;border:none;
                          padding:2px 8px;border-radius:2px;font-size:11px; }
            QPushButton:hover   { background:#4a4a4a; }
            QPushButton:checked { background:#214283; }
            QComboBox { background:#3a3a3a;color:#a9b7c6;border:1px solid #444;padding:1px 3px; }
            QComboBox::drop-down { border:none; width:14px; }
            QComboBox QAbstractItemView { background:#2b2b2b;color:#a9b7c6;
                                          selection-background-color:#214283; }
            QLineEdit { background:#333;color:#a9b7c6;border:1px solid #444;padding:1px 3px; }
            QStatusBar { background:#252525;color:#808080; }
            QSplitter::handle { background:#2a2a2a; }
            QSplitter::handle:horizontal { width:2px; }
            QSplitter::handle:vertical   { height:3px; }
            QScrollBar:vertical   { background:#1e1e1e;width:6px; }
            QScrollBar::handle:vertical { background:#3a3a3a;border-radius:3px; }
            QScrollBar:horizontal { background:#1e1e1e;height:6px; }
            QScrollBar::handle:horizontal { background:#3a3a3a;border-radius:3px; }
        """)


# ---------------------------------------------------------------------------
# エントリーポイント
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setApplicationName("SSH Log Viewer")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
