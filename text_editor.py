#!/usr/bin/env python3
"""Sora Editor — マルチタブ・FTP対応のテキストエディタ"""
__version__ = "1.1.21"

import sys
import os
import ftplib
import io
import json
import re
import fnmatch
import difflib

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QTabWidget, QWidget, QVBoxLayout,
    QHBoxLayout, QPlainTextEdit, QTextEdit, QFileDialog, QDialog, QLabel,
    QLineEdit, QPushButton, QCheckBox, QStatusBar,
    QSplitter, QListWidget, QListWidgetItem,
    QMessageBox, QGridLayout, QComboBox, QInputDialog,
    QTreeWidget, QTreeWidgetItem, QSpinBox, QTextBrowser, QFrame,
    QStackedWidget, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QProgressDialog, QStyledItemDelegate, QStyle,
    QStyleOptionViewItem, QSizePolicy, QScrollArea, QTableView, QMenu,
)
from PyQt6.QtCore import Qt, QRegularExpression, pyqtSignal, QSize, QThread, QTimer, QFileSystemWatcher
from PyQt6.QtGui import (
    QFont, QFontMetrics, QColor, QTextCharFormat, QSyntaxHighlighter,
    QKeySequence, QAction, QPainter, QTextFormat, QTextDocument, QPixmap,
    QStandardItemModel, QStandardItem,
)


# ---------------------------------------------------------------------------
# アプリ設定 (フォントサイズ + テーマ) — ssh_log_viewer と同じ思想
# ---------------------------------------------------------------------------

_SETTINGS_PATH = os.path.join(os.path.expanduser('~'), '.text_editor_settings.json')

_THEME_PRESETS = {
    'Dark': {
        'bg':            '#2b2b2b',
        'panel_bg':      '#252525',
        'editor_bg':     '#2b2b2b',
        'toolbar_bg':    '#2f2f2f',
        'text':          '#a9b7c6',
        'text_dim':      '#808080',
        'selection':     '#214283',
        'border':        '#444444',
        'control_bg':    '#3a3a3a',
        'control_hover': '#4a4a4a',
        'line_highlight':'#4d5b73',   # 元 #3a3a3a (背景に同化) → 青みのある明るめに
        'gutter_bg':     '#2b2b2b',
        'gutter_fg':     '#606060',
    },
    'Dark Blue': {
        'bg':            '#0e1525',
        'panel_bg':      '#131c2f',
        'editor_bg':     '#0e1525',
        'toolbar_bg':    '#172238',
        'text':          '#c0d0e8',
        'text_dim':      '#7080a0',
        'selection':     '#2a4a8a',
        'border':        '#1f2d4a',
        'control_bg':    '#1f2d4a',
        'control_hover': '#2a3d60',
        'line_highlight':'#2c4476',   # 元 #1a2640 → よりはっきり
        'gutter_bg':     '#0e1525',
        'gutter_fg':     '#506080',
    },
    'High Contrast': {
        'bg':            '#000000',
        'panel_bg':      '#0a0a0a',
        'editor_bg':     '#000000',
        'toolbar_bg':    '#151515',
        'text':          '#ffffff',
        'text_dim':      '#a0a0a0',
        'selection':     '#0066cc',
        'border':        '#444444',
        'control_bg':    '#2a2a2a',
        'control_hover': '#3a3a3a',
        'line_highlight':'#3a3a3a',   # 元 #202020 → くっきり
        'gutter_bg':     '#000000',
        'gutter_fg':     '#888888',
    },
    'Monochrome': {
        'bg':            '#1c1c1c',
        'panel_bg':      '#222222',
        'editor_bg':     '#1c1c1c',
        'toolbar_bg':    '#2a2a2a',
        'text':          '#cccccc',
        'text_dim':      '#888888',
        'selection':     '#505050',
        'border':        '#3a3a3a',
        'control_bg':    '#3a3a3a',
        'control_hover': '#4a4a4a',
        'line_highlight':'#4a4a4a',   # 元 #303030 → より目立つ
        'gutter_bg':     '#1c1c1c',
        'gutter_fg':     '#666666',
    },
    'Light': {
        'bg':            '#f4f4f4',
        'panel_bg':      '#ffffff',
        'editor_bg':     '#ffffff',
        'toolbar_bg':    '#e6e6e6',
        'text':          '#1e1e1e',
        'text_dim':      '#666666',
        'selection':     '#cfe5ff',
        'border':        '#cccccc',
        'control_bg':    '#dcdcdc',
        'control_hover': '#c8c8c8',
        'line_highlight':'#d6e6f5',   # 元 #eef2f8 (白に同化) → 青みのある淡色
        'gutter_bg':     '#e0e0e0',   # 元 #f0f0f0 → 行番号と差を確保
        'gutter_fg':     '#444444',   # 元 #888888 → 可読性向上
    },
    'Solarized Light': {
        'bg':            '#fdf6e3',
        'panel_bg':      '#eee8d5',
        'editor_bg':     '#fdf6e3',
        'toolbar_bg':    '#e4dcc3',
        'text':          '#586e75',
        'text_dim':      '#657b83',
        'selection':     '#cfd9c4',
        'border':        '#a89a72',
        'control_bg':    '#e4dcc3',
        'control_hover': '#d4cba8',
        'line_highlight':'#d6cfb3',   # 元 #eee8d5 → 一段濃く
        'gutter_bg':     '#dcd6c1',   # 元 #eee8d5 → 編集領域(#fdf6e3) との差を確保
        'gutter_fg':     '#586e75',   # 元 #93a1a1 → 可読性向上 (text と同色)
    },
}

_DEFAULT_SETTINGS = {
    'editor_font_size': 15,   # px 指定 (旧 11pt ≈ 15px 相当)
    'ui_font_size':     10,
    'theme':            'Dark',
    # ログ→ソースジャンプ用に登録するソースルートDIRの一覧 (再帰検索の起点)
    'source_dirs':      [],
    # FTP ファイル一覧の時刻表示方式:
    #   'local' (推奨) : サーバー出力 (LIST / MLSD) を UTC とみなして
    #                    OS のローカル TZ へ変換 (FFFTP の TZ=GMT 設定 +
    #                    UTC→JST 変換と同じ挙動。 大半のサーバーが UTC 報告)
    #   'raw'          : LIST / MLSD 値を加工せず生表示
    #                    (サーバーが既にローカル TZ で報告している環境向け)
    'ftp_time_mode':    'local',
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


SETTINGS: dict = _load_settings()


# ---------------------------------------------------------------------------
# ブックマークの永続化 ( {絶対パス: [行番号, ...]} を JSON 保存)
# ---------------------------------------------------------------------------
_BOOKMARKS_PATH = os.path.join(os.path.expanduser('~'), '.text_editor_bookmarks.json')


def _load_bookmarks_store() -> dict:
    try:
        with open(_BOOKMARKS_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_bookmarks_store(store: dict):
    try:
        with open(_BOOKMARKS_PATH, 'w', encoding='utf-8') as f:
            json.dump(store, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 最近開いたファイル (絶対パス x N、開いた順) を JSON で永続化
# ---------------------------------------------------------------------------
_RECENT_FILES_PATH = os.path.join(os.path.expanduser('~'), '.text_editor_recent_files.json')
_RECENT_FILES_MAX  = 15


def _load_recent_files() -> list[str]:
    try:
        with open(_RECENT_FILES_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return [p for p in data if isinstance(p, str)] if isinstance(data, list) else []
    except Exception:
        return []


def _save_recent_files(paths: list[str]):
    try:
        with open(_RECENT_FILES_PATH, 'w', encoding='utf-8') as f:
            json.dump(paths[:_RECENT_FILES_MAX], f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _push_recent_file(path: str) -> list[str]:
    """履歴を更新 (path を先頭に、重複は除去、最大 _RECENT_FILES_MAX 件)。
    保存も同時に行い、最新の履歴リストを返す。"""
    if not path:
        return _load_recent_files()
    try:
        path = os.path.abspath(path)
    except Exception:
        return _load_recent_files()
    items = _load_recent_files()
    # 大文字小文字を吸収しつつ既存エントリを除去 (Windows 想定)
    norm = os.path.normcase(path)
    items = [p for p in items if os.path.normcase(p) != norm]
    items.insert(0, path)
    items = items[:_RECENT_FILES_MAX]
    _save_recent_files(items)
    return items


def _theme() -> dict:
    return _THEME_PRESETS.get(SETTINGS.get('theme', 'Dark'), _THEME_PRESETS['Dark'])


def _is_light_theme() -> bool:
    """現在のテーマ背景が明るいか (輝度で判定)。"""
    bg = _theme().get('bg', '#2b2b2b').lstrip('#')
    try:
        r, g, b = int(bg[0:2], 16), int(bg[2:4], 16), int(bg[4:6], 16)
        return (0.299 * r + 0.587 * g + 0.114 * b) > 140
    except Exception:
        return False


def _syntax_palette() -> dict:
    """シンタックスハイライトのトークン配色をテーマ明暗に合わせて返す。
    ダーク基調はそのまま、ライト基調では濃いめの高コントラスト色にする。
    """
    if _is_light_theme():
        return {'keyword': '#0033B3', 'type': '#006A6A', 'function': '#795E26',
                'number': '#0B6FC2', 'string': '#1A7F1A', 'comment': '#6A737D'}
    return {'keyword': '#CC7832', 'type': '#4EC9B0', 'function': '#DCDCAA',
            'number': '#6897BB', 'string': '#6A8759', 'comment': '#808080'}


# ---------------------------------------------------------------------------
# 一時ファイルのクリーンアップ (FTP ダウンロード分)
# ---------------------------------------------------------------------------

_TEMP_RETENTION_DAYS = 7   # 7日以上前の一時ファイルは起動時に自動削除


# ---------------------------------------------------------------------------
# 検索・置換履歴の永続化
# ---------------------------------------------------------------------------

_SEARCH_HISTORY_PATH = os.path.join(os.path.expanduser('~'), '.text_editor_history.json')
_HISTORY_MAX = 30


def _load_search_history() -> dict:
    try:
        with open(_SEARCH_HISTORY_PATH, 'r', encoding='utf-8') as f:
            d = json.load(f)
            return {
                'search':  list(d.get('search', []))[:_HISTORY_MAX],
                'replace': list(d.get('replace', []))[:_HISTORY_MAX],
            }
    except Exception:
        return {'search': [], 'replace': []}


def _save_search_history():
    try:
        with open(_SEARCH_HISTORY_PATH, 'w', encoding='utf-8') as f:
            json.dump(SEARCH_HISTORY, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


SEARCH_HISTORY: dict = _load_search_history()


def _cleanup_old_temp_files(base_dir: str, max_age_days: int = _TEMP_RETENTION_DAYS):
    """指定 dir 配下で更新日時 max_age_days 日以上前のファイルを削除し、
    空になったディレクトリも削除する。"""
    import time as _time
    if not os.path.isdir(base_dir):
        return 0
    cutoff = _time.time() - max_age_days * 86400
    removed = 0
    for root, dirs, files in os.walk(base_dir, topdown=False):
        for fname in files:
            fpath = os.path.join(root, fname)
            try:
                if os.path.getmtime(fpath) < cutoff:
                    os.remove(fpath)
                    removed += 1
            except Exception:
                pass
        # 空ディレクトリも除去
        try:
            if not os.listdir(root) and root != base_dir:
                os.rmdir(root)
        except Exception:
            pass
    return removed


# ---------------------------------------------------------------------------
# 行番号エリア
# ---------------------------------------------------------------------------

class LineNumberArea(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self):
        return QSize(self.editor.line_number_area_width(), 0)

    def paintEvent(self, event):
        self.editor.line_number_area_paint_event(event)


# ---------------------------------------------------------------------------
# コードエディタ（行番号付き）
# ---------------------------------------------------------------------------

class CodeEditor(QPlainTextEdit):
    bookmark_toggled = pyqtSignal(int, bool)   # lineno, is_bookmarked
    sql_extract_requested = pyqtSignal()       # 選択範囲からSQL抽出 (右クリック)
    source_open_requested = pyqtSignal()       # 選択範囲/現在行からソースを開く (右クリック)

    _GUTTER_W   = 7    # 変更バー幅(px) — 4 → 7 に拡大
    _BOOKMARK_W = 12   # ブックマーク列幅(px)
    # 変更ガター色 — VS Code 風の鮮やかさ
    _GUTTER_COLORS = {
        'added':    QColor("#4CAF50"),   # 緑 (新規)
        'modified': QColor("#FFB74D"),   # オレンジ (変更)
        'deleted':  QColor("#E53935"),   # 赤 (削除)
    }
    # 行背景の淡い色 (ガターと連動して行全体を薄く塗る)
    _LINE_BG_COLORS = {
        'added':    QColor(76, 175, 80, 30),   # 緑 alpha 30/255
        'modified': QColor(255, 183, 77, 30),  # オレンジ
        'deleted':  QColor(229, 57, 53, 35),   # 赤
    }
    _BOOKMARK_COLOR = QColor("#4A9EFF")

    def __init__(self):
        super().__init__()
        self.line_number_area = LineNumberArea(self)
        self._change_map: dict[int, str] = {}
        self._bookmarks: set[int] = set()
        self._search_selections: list = []

        fs = SETTINGS.get('editor_font_size', 15)
        font = QFont("Consolas")
        font.setPixelSize(fs)   # px 指定 (設定ラベルの「px」と一致 / 段差を均一に)
        font.setFixedPitch(True)
        self.setFont(font)
        self.setTabStopDistance(4 * self.fontMetrics().horizontalAdvance(' '))

        self.blockCountChanged.connect(self.update_line_number_area_width)
        self.updateRequest.connect(self.update_line_number_area)
        self.cursorPositionChanged.connect(self.highlight_current_line)

        self.update_line_number_area_width(0)
        self.highlight_current_line()

    # --- 変更ガター ---

    def set_change_map(self, change_map: dict):
        self._change_map = change_map
        self.line_number_area.update()
        # 行背景の選択範囲も再構築
        self.highlight_current_line()

    def goto_next_change(self, forward: bool = True):
        """次/前の変更箇所 (added/modified/deleted) にカーソルを移動"""
        if not self._change_map:
            return
        current = self.textCursor().blockNumber() + 1
        ordered = sorted(self._change_map.keys())
        if forward:
            candidates = [n for n in ordered if n > current]
            target = candidates[0] if candidates else ordered[0]   # 折り返し
        else:
            candidates = [n for n in ordered if n < current]
            target = candidates[-1] if candidates else ordered[-1]
        block = self.document().findBlockByNumber(target - 1)
        if block.isValid():
            cur = self.textCursor()
            cur.setPosition(block.position())
            self.setTextCursor(cur)
            self.centerCursor()

    # --- ブックマーク ---

    def toggle_bookmark(self):
        lineno = self.textCursor().blockNumber() + 1
        if lineno in self._bookmarks:
            self._bookmarks.discard(lineno)
            self.bookmark_toggled.emit(lineno, False)
        else:
            self._bookmarks.add(lineno)
            self.bookmark_toggled.emit(lineno, True)
        self.line_number_area.update()

    def add_bookmark(self, lineno: int):
        """指定行にブックマークを追加 (既にあれば何もしない)。
        ソースジャンプ等から自動でしおりを付けるのに使う。
        """
        if lineno < 1 or lineno in self._bookmarks:
            return
        self._bookmarks.add(lineno)
        self.bookmark_toggled.emit(lineno, True)
        self.line_number_area.update()

    def goto_next_bookmark(self, forward: bool = True):
        if not self._bookmarks:
            return
        current = self.textCursor().blockNumber() + 1
        ordered = sorted(self._bookmarks)
        if forward:
            candidates = [b for b in ordered if b > current]
            target = candidates[0] if candidates else ordered[0]
        else:
            candidates = [b for b in ordered if b < current]
            target = candidates[-1] if candidates else ordered[-1]
        block = self.document().findBlockByNumber(target - 1)
        if block.isValid():
            cur = self.textCursor()
            cur.setPosition(block.position())
            self.setTextCursor(cur)
            self.centerCursor()

    def goto_next_error(self, forward: bool = True):
        """ERROR/WARN/EXCEPTION を含む行へ移動"""
        pat = re.compile(r'\b(?:ERROR|CRITICAL|FATAL|EXCEPTION|WARN(?:ING)?)\b', re.IGNORECASE)
        doc = self.document()
        total = doc.blockCount()
        current = self.textCursor().blockNumber()
        rng = range(current + 1, total) if forward else range(current - 1, -1, -1)
        for i in rng:
            block = doc.findBlockByNumber(i)
            if pat.search(block.text()):
                cur = self.textCursor()
                cur.setPosition(block.position())
                self.setTextCursor(cur)
                self.centerCursor()
                return
        # 折り返し
        rng2 = range(0, current) if forward else range(total - 1, current, -1)
        for i in rng2:
            block = doc.findBlockByNumber(i)
            if pat.search(block.text()):
                cur = self.textCursor()
                cur.setPosition(block.position())
                self.setTextCursor(cur)
                self.centerCursor()
                return

    # --- ガター描画 ---

    def line_number_area_width(self):
        digits = len(str(max(1, self.blockCount())))
        return self._GUTTER_W + 2 + self._BOOKMARK_W + 4 + self.fontMetrics().horizontalAdvance('9') * digits

    def update_line_number_area_width(self, _):
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def update_line_number_area(self, rect, dy):
        if dy:
            self.line_number_area.scroll(0, dy)
        else:
            self.line_number_area.update(
                0, rect.y(), self.line_number_area.width(), rect.height()
            )
        if rect.contains(self.viewport().rect()):
            self.update_line_number_area_width(0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self.line_number_area.setGeometry(
            cr.left(), cr.top(), self.line_number_area_width(), cr.height()
        )

    def contextMenuEvent(self, event):
        # Qt 標準メニューは英語ラベルなので、編集メニューと表記を揃えるため
        # 日本語のカスタムコンテキストメニューを自前で構築する。
        from PyQt6.QtWidgets import QMenu
        from PyQt6.QtGui import QGuiApplication

        menu = QMenu(self)
        doc = self.document()
        has_sel = self.textCursor().hasSelection()
        editable = not self.isReadOnly()
        clip = QGuiApplication.clipboard()
        clip_has_text = bool(clip and clip.text())

        a_undo = menu.addAction("元に戻す")
        a_undo.setEnabled(editable and doc.isUndoAvailable())
        a_undo.triggered.connect(self.undo)

        a_redo = menu.addAction("やり直し")
        a_redo.setEnabled(editable and doc.isRedoAvailable())
        a_redo.triggered.connect(self.redo)

        menu.addSeparator()

        a_cut = menu.addAction("切り取り")
        a_cut.setEnabled(editable and has_sel)
        a_cut.triggered.connect(self.cut)

        a_copy = menu.addAction("コピー")
        a_copy.setEnabled(has_sel)
        a_copy.triggered.connect(self.copy)

        a_paste = menu.addAction("貼り付け")
        a_paste.setEnabled(editable and clip_has_text)
        a_paste.triggered.connect(self.paste)

        a_del = menu.addAction("削除")
        a_del.setEnabled(editable and has_sel)
        a_del.triggered.connect(lambda: self.textCursor().removeSelectedText())

        menu.addSeparator()

        a_all = menu.addAction("すべて選択")
        a_all.triggered.connect(self.selectAll)

        menu.addSeparator()

        a_sql = menu.addAction("選択範囲からSQL抽出...")
        a_sql.setEnabled(has_sel)
        if not has_sel:
            a_sql.setToolTip("先にSQLを含むログ範囲を選択してください")
        a_sql.triggered.connect(self.sql_extract_requested.emit)

        a_src = menu.addAction("ソースを開く (該当行へジャンプ)...")
        a_src.setToolTip(
            "選択範囲 (無ければ現在行) の Class#method():行 / スタックトレース等を解析し、\n"
            "登録済みソース検索パスから該当ファイルを開いてその行へジャンプします")
        a_src.triggered.connect(self.source_open_requested.emit)

        menu.exec(event.globalPos())

    def inputMethodEvent(self, event):
        # IME 変換中 (preedit) のテキスト色は IME 由来の QTextCharFormat で
        # 塗られ、Light テーマでは前景・背景がコントラスト不足で文字が
        # 脱色して読めなくなる。テーマの text/editor_bg を明示する
        # TextFormat を生成し、IME の TextFormat 属性を全置換する
        # (下線等の意味伝達は残すため underline は維持)。
        try:
            from PyQt6.QtGui import QInputMethodEvent, QTextCharFormat
            t = _theme()
            preedit = event.preeditString()
            new_attrs = []
            saw_text_format = False
            for a in event.attributes():
                if a.type == QInputMethodEvent.AttributeType.TextFormat:
                    saw_text_format = True
                    fmt = QTextCharFormat()
                    fmt.setForeground(QColor(t['text']))
                    fmt.setBackground(QColor(t['editor_bg']))
                    # IME が下線を要求している場合は維持
                    if isinstance(a.value, QTextCharFormat) and a.value.fontUnderline():
                        fmt.setFontUnderline(True)
                        fmt.setUnderlineColor(QColor(t['text']))
                    new_attrs.append(QInputMethodEvent.Attribute(
                        a.type, a.start, a.length, fmt,
                    ))
                else:
                    new_attrs.append(a)
            # TextFormat 属性が皆無で preedit がある場合は、preedit 全域に
            # デフォルト fmt を被せて Qt の暗黙描画 (白) を回避する。
            if not saw_text_format and preedit:
                fmt = QTextCharFormat()
                fmt.setForeground(QColor(t['text']))
                fmt.setBackground(QColor(t['editor_bg']))
                fmt.setFontUnderline(True)
                fmt.setUnderlineColor(QColor(t['text']))
                new_attrs.append(QInputMethodEvent.Attribute(
                    QInputMethodEvent.AttributeType.TextFormat,
                    0, len(preedit), fmt,
                ))
            patched = QInputMethodEvent(preedit, new_attrs)
            patched.setCommitString(
                event.commitString(),
                event.replacementStart(),
                event.replacementLength(),
            )
            super().inputMethodEvent(patched)
        except Exception:
            super().inputMethodEvent(event)

    def paintEvent(self, event):
        # テキスト描画完了後に「現在行」を強調する。
        # 半透明背景で塗ると文字が脱色されるため、**上下ボーダー + 左端バー**
        # の枠線スタイルにする。文字は一切被覆されず、行の境界だけ可視化。
        super().paintEvent(event)
        try:
            cur_rect = self.cursorRect()
        except Exception:
            return
        from PyQt6.QtGui import QPainter as _QPainter
        is_light = SETTINGS.get('theme', 'Dark') in ('Light', 'Solarized Light')
        accent = QColor("#1976D2") if is_light else QColor("#4A90E2")
        painter = _QPainter(self.viewport())
        vp_w = self.viewport().width()
        top = cur_rect.top()
        bot = cur_rect.top() + cur_rect.height() - 1
        # 上下に 1px の細いボーダー (= 行の境界をはっきりさせる)
        painter.fillRect(0, top, vp_w, 1, accent)
        painter.fillRect(0, bot, vp_w, 1, accent)
        # 左端に 3px の太いアクセントバー (= ガター側にも視線誘導)
        painter.fillRect(0, top, 3, cur_rect.height(), accent)
        painter.end()

    def line_number_area_paint_event(self, event):
        painter = QPainter(self.line_number_area)
        t = _theme()
        painter.fillRect(event.rect(), QColor(t['gutter_bg']))

        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = round(
            self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
        )
        bottom = top + round(self.blockBoundingRect(block).height())
        line_h = self.fontMetrics().height()
        gw  = self._GUTTER_W
        bw  = self._BOOKMARK_W
        area_w = self.line_number_area.width()
        # 各列の開始X
        bm_x  = gw + 2          # ブックマーク列
        num_x = bm_x + bw + 2   # 行番号列

        # 現在のカーソル行 (1-based)
        current_lineno = self.textCursor().blockNumber() + 1
        # Light テーマでは黄色 #FFEB3B は薄い背景にほぼ同化するため、
        # 視認性の高い濃いオレンジに切り替える。
        is_light = SETTINGS.get('theme', 'Dark') in ('Light', 'Solarized Light')
        current_accent = QColor("#E65100") if is_light else QColor("#FFEB3B")

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                lineno = block_number + 1
                is_current = (lineno == current_lineno)

                # 現在行のガター背景を強調 (テーマに応じた淡いアクセント色帯)
                if is_current:
                    # 黄 (Dark) or 濃オレンジ (Light) の薄い帯
                    accent_band = QColor(current_accent)
                    accent_band.setAlpha(60)
                    painter.fillRect(
                        num_x - 2, top, area_w - (num_x - 2), line_h, accent_band,
                    )

                # 変更バー
                kind = self._change_map.get(lineno)
                if kind in self._GUTTER_COLORS:
                    painter.fillRect(0, top, gw, line_h, self._GUTTER_COLORS[kind])

                # 現在行アクセントバー (左端の太い縦線、変更バーとは別位置に薄く重ねる)
                if is_current:
                    # 変更バーがある場合は右側に、ない場合は同じ位置に細く描画
                    bar_x = gw if kind in self._GUTTER_COLORS else 0
                    painter.fillRect(bar_x, top, 3, line_h, current_accent)

                # ブックマーク（青菱形）
                if lineno in self._bookmarks:
                    painter.save()
                    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(self._BOOKMARK_COLOR)
                    cx = bm_x + bw // 2
                    cy = top + line_h // 2
                    d = 4
                    from PyQt6.QtGui import QPolygonF
                    from PyQt6.QtCore import QPointF
                    diamond = QPolygonF([
                        QPointF(cx,     cy - d),
                        QPointF(cx + d, cy),
                        QPointF(cx,     cy + d),
                        QPointF(cx - d, cy),
                    ])
                    painter.drawPolygon(diamond)
                    painter.restore()

                # 行番号 (現在行はテーマアクセント色 + 太字で強調)
                if is_current:
                    painter.setPen(current_accent)
                    f = QFont(self.font()); f.setBold(True)
                    painter.setFont(f)
                else:
                    painter.setPen(QColor(t['gutter_fg']))
                    painter.setFont(self.font())
                painter.drawText(
                    num_x, top, area_w - num_x - 2, line_h,
                    Qt.AlignmentFlag.AlignRight,
                    str(lineno),
                )
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            block_number += 1

    def set_search_highlights(self, selections: list):
        self._search_selections = selections
        self.highlight_current_line()

    def highlight_current_line(self):
        # 現在行の full-width 背景は paintEvent() で描く (文字の前に背景を
        # 入れて脱色させない)。ExtraSelections では change_map と
        # 検索マッチのみを扱う。
        # 行が変わったら viewport を再描画して現在行ハイライトを更新。
        self.viewport().update()
        extra = []

        # 2. 変更行の薄い背景着色 (added/modified/deleted)
        if self._change_map:
            doc = self.document()
            for lineno, kind in self._change_map.items():
                color = self._LINE_BG_COLORS.get(kind)
                if not color:
                    continue
                block = doc.findBlockByNumber(lineno - 1)
                if not block.isValid():
                    continue
                sel = QTextEdit.ExtraSelection()
                sel.format.setBackground(color)
                sel.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
                cur = self.textCursor()
                cur.setPosition(block.position())
                sel.cursor = cur
                extra.append(sel)

        # 3. 検索ハイライト (= 一番上)。FullWidthSelection より優先される
        #    通常の選択範囲なので、現在行の薄い背景の上に黄色マッチが乗る。
        extra.extend(self._search_selections)

        self.setExtraSelections(extra)
        # カーソル行が変わったらガター側 (現在行アクセントバー / 行番号強調) も
        # 再描画する必要がある
        self.line_number_area.update()


# ---------------------------------------------------------------------------
# シンタックスハイライター
# ---------------------------------------------------------------------------

class SyntaxHighlighter(QSyntaxHighlighter):
    LANG_RULES = {
        'python': {
            'keywords': [
                'False', 'None', 'True', 'and', 'as', 'assert', 'async', 'await',
                'break', 'class', 'continue', 'def', 'del', 'elif', 'else', 'except',
                'finally', 'for', 'from', 'global', 'if', 'import', 'in', 'is',
                'lambda', 'nonlocal', 'not', 'or', 'pass', 'raise', 'return', 'try',
                'while', 'with', 'yield',
            ],
            'strings': [r'"[^"\\]*(\\.[^"\\]*)*"', r"'[^'\\]*(\\.[^'\\]*)*'"],
            'comment': r'#[^\n]*',
        },
        'javascript': {
            'keywords': [
                'break', 'case', 'catch', 'class', 'const', 'continue', 'debugger',
                'default', 'delete', 'do', 'else', 'export', 'extends', 'finally',
                'for', 'function', 'if', 'import', 'in', 'instanceof', 'let', 'new',
                'of', 'return', 'static', 'super', 'switch', 'this', 'throw', 'try',
                'typeof', 'var', 'void', 'while', 'with', 'async', 'await', 'yield',
            ],
            'strings': [r'"[^"\\]*(\\.[^"\\]*)*"', r"'[^'\\]*(\\.[^'\\]*)*'",
                        r'`[^`\\]*(\\.[^`\\]*)*`'],
            'comment': r'//[^\n]*',
            'block_comment': ('/*', '*/'),
        },
        'log': {
            # 行全体をレベルで色分け（最初にマッチしたものを適用）
            # 背景色は使わない (= None): 行全体に bg を塗ると、後段の inline
            # ルール (timestamp / thread name 等) が setFormat で前景色だけを
            # 差し替える際に bg が剥がれ、ストライプ状の縞模様になる。
            # ログレベルは前景色のみで識別する。
            'line_levels': [
                (r'\b(?:ERROR|CRITICAL|FATAL|SEVERE)\b',  None, '#FF7070'),
                (r'\b(?:WARN(?:ING)?)\b',                 None, '#E8B26A'),
                (r'\b(?:INFO|INFORMATION)\b',             None, '#6A9F6A'),
                (r'\b(?:DEBUG)\b',                        None, '#707070'),
                (r'\b(?:TRACE|VERBOSE)\b',                None, '#555555'),
            ],
            # 行内の特定パターン
            'inline': [
                # タイムスタンプ
                (r'\d{4}[-/]\d{2}[-/]\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:\d{2})?', '#4EC9B0'),
                (r'\b\d{2}:\d{2}:\d{2}(?:[.,]\d+)?\b',  '#4EC9B0'),
                # スレッド名・ロガー名 [xxx]
                (r'\[[\w\s.:\-/]+\]',                    '#9876AA'),
                # Exception クラス名
                (r'\b\w+(?:Exception|Error)\b',          '#FF7070'),
                # スタックトレース
                (r'^\s+at\s+[\w.$<>()\[\]/]+',           '#CC7832'),
                (r'^\s+Caused by:',                      '#FF7070'),
                # IPアドレス
                (r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', '#4EC9B0'),
                # HTTPステータスコード(4xx/5xx)ハイライトは産業ログで誤検出多発のため無効化
            ],
            'kw_case_insensitive': False,
        },
        'sql': {
            'keywords': [
                'SELECT', 'FROM', 'WHERE', 'AND', 'OR', 'NOT', 'IN', 'IS', 'NULL',
                'INSERT', 'INTO', 'VALUES', 'UPDATE', 'SET', 'DELETE', 'TRUNCATE',
                'CREATE', 'TABLE', 'DROP', 'ALTER', 'ADD', 'COLUMN', 'MODIFY',
                'INDEX', 'VIEW', 'DATABASE', 'SCHEMA', 'SEQUENCE', 'TRIGGER',
                'JOIN', 'INNER', 'LEFT', 'RIGHT', 'FULL', 'OUTER', 'CROSS',
                'ON', 'USING', 'AS', 'DISTINCT', 'ALL', 'TOP',
                'GROUP', 'BY', 'ORDER', 'HAVING', 'LIMIT', 'OFFSET', 'FETCH', 'NEXT', 'ROWS', 'ONLY',
                'UNION', 'EXCEPT', 'INTERSECT',
                'BEGIN', 'COMMIT', 'ROLLBACK', 'TRANSACTION', 'SAVEPOINT',
                'CASE', 'WHEN', 'THEN', 'ELSE', 'END',
                'EXISTS', 'BETWEEN', 'LIKE', 'ILIKE', 'ESCAPE',
                'PRIMARY', 'KEY', 'FOREIGN', 'REFERENCES', 'UNIQUE', 'DEFAULT',
                'CHECK', 'CONSTRAINT', 'NOT', 'NULL',
                'WITH', 'RECURSIVE', 'OVER', 'PARTITION', 'ROW', 'RANGE',
                'GRANT', 'REVOKE', 'PRIVILEGES', 'TO', 'PUBLIC',
                'IF', 'REPLACE', 'MERGE', 'MATCHED',
            ],
            'types': [
                'INT', 'INTEGER', 'BIGINT', 'SMALLINT', 'TINYINT', 'MEDIUMINT',
                'FLOAT', 'DOUBLE', 'DECIMAL', 'NUMERIC', 'REAL', 'MONEY', 'SMALLMONEY',
                'CHAR', 'VARCHAR', 'TEXT', 'NVARCHAR', 'NCHAR', 'NTEXT', 'CLOB',
                'DATE', 'TIME', 'DATETIME', 'TIMESTAMP', 'INTERVAL', 'YEAR',
                'BOOLEAN', 'BOOL', 'BIT',
                'BINARY', 'VARBINARY', 'BLOB', 'BYTEA',
                'SERIAL', 'BIGSERIAL', 'AUTO_INCREMENT',
                'JSON', 'JSONB', 'XML', 'UUID',
                'ARRAY', 'ENUM',
            ],
            'functions': [
                'COUNT', 'SUM', 'AVG', 'MIN', 'MAX',
                'COALESCE', 'NULLIF', 'IFNULL', 'NVL', 'IIF',
                'UPPER', 'LOWER', 'TRIM', 'LTRIM', 'RTRIM', 'LPAD', 'RPAD',
                'LENGTH', 'LEN', 'SUBSTRING', 'SUBSTR', 'CONCAT', 'REPLACE',
                'CHARINDEX', 'INSTR', 'POSITION', 'STRPOS',
                'NOW', 'GETDATE', 'CURDATE', 'CURTIME', 'SYSDATE',
                'DATEADD', 'DATEDIFF', 'DATEPART', 'DATE_PART', 'EXTRACT',
                'CAST', 'CONVERT', 'TRY_CAST', 'TO_CHAR', 'TO_DATE', 'TO_NUMBER',
                'ROW_NUMBER', 'RANK', 'DENSE_RANK', 'NTILE', 'LEAD', 'LAG',
                'FIRST_VALUE', 'LAST_VALUE', 'CUME_DIST', 'PERCENT_RANK',
                'ROUND', 'FLOOR', 'CEIL', 'CEILING', 'ABS', 'MOD', 'POWER', 'SQRT',
                'STRING_AGG', 'GROUP_CONCAT', 'LISTAGG',
                'DECODE', 'GREATEST', 'LEAST',
            ],
            'strings': [r"'(?:[^'\\]|\\.)*'"],
            'comment': r'--[^\n]*',
            'block_comment': ('/*', '*/'),
            'kw_case_insensitive': True,
        },
        'cpp': {
            'keywords': [
                'alignas', 'alignof', 'asm', 'auto', 'break', 'case', 'catch',
                'class', 'concept', 'const', 'consteval', 'constexpr', 'constinit',
                'const_cast', 'continue', 'decltype', 'default', 'delete', 'do',
                'dynamic_cast', 'else', 'enum', 'explicit', 'export', 'extern',
                'false', 'for', 'friend', 'goto', 'if', 'inline', 'mutable',
                'namespace', 'new', 'noexcept', 'nullptr', 'operator', 'private',
                'protected', 'public', 'register', 'reinterpret_cast', 'requires',
                'return', 'sizeof', 'static', 'static_assert', 'static_cast',
                'struct', 'switch', 'template', 'this', 'thread_local', 'throw',
                'true', 'try', 'typedef', 'typeid', 'typename', 'union', 'using',
                'virtual', 'volatile', 'while',
            ],
            'types': [
                'bool', 'char', 'char8_t', 'char16_t', 'char32_t', 'double',
                'float', 'int', 'long', 'short', 'signed', 'unsigned', 'void',
                'wchar_t', 'size_t', 'ssize_t', 'int8_t', 'int16_t', 'int32_t',
                'int64_t', 'uint8_t', 'uint16_t', 'uint32_t', 'uint64_t',
                'string', 'wstring', 'vector', 'map', 'set', 'list', 'pair',
            ],
            'patterns': [
                (r'^\s*#\s*\w+', '#9876AA'),   # プリプロセッサ (#include / #define 等)
            ],
            'strings': [r'"(?:[^"\\]|\\.)*"', r"'(?:[^'\\]|\\.)*'"],
            'comment': r'//[^\n]*',
            'block_comment': ('/*', '*/'),
        },
        'java': {
            'keywords': [
                'abstract', 'assert', 'break', 'case', 'catch', 'class', 'const',
                'continue', 'default', 'do', 'else', 'enum', 'extends', 'final',
                'finally', 'for', 'goto', 'if', 'implements', 'import',
                'instanceof', 'interface', 'native', 'new', 'package', 'private',
                'protected', 'public', 'return', 'static', 'strictfp', 'super',
                'switch', 'synchronized', 'this', 'throw', 'throws', 'transient',
                'try', 'volatile', 'while', 'true', 'false', 'null', 'var',
                'record', 'sealed', 'yield', 'permits', 'non-sealed',
            ],
            'types': [
                'boolean', 'byte', 'char', 'double', 'float', 'int', 'long',
                'short', 'void', 'String', 'Integer', 'Long', 'Double', 'Float',
                'Boolean', 'Byte', 'Short', 'Character', 'Object', 'List', 'Map',
                'Set', 'Collection', 'Optional',
            ],
            'patterns': [
                (r'@\w+', '#BBB529'),           # アノテーション (@Override 等)
            ],
            'strings': [r'"(?:[^"\\]|\\.)*"', r"'(?:[^'\\]|\\.)*'"],
            'comment': r'//[^\n]*',
            'block_comment': ('/*', '*/'),
        },
        'csharp': {
            'keywords': [
                'abstract', 'as', 'base', 'break', 'case', 'catch', 'checked',
                'class', 'const', 'continue', 'default', 'delegate', 'do', 'else',
                'enum', 'event', 'explicit', 'extern', 'false', 'finally', 'fixed',
                'for', 'foreach', 'goto', 'if', 'implicit', 'in', 'interface',
                'internal', 'is', 'lock', 'namespace', 'new', 'null', 'operator',
                'out', 'override', 'params', 'private', 'protected', 'public',
                'readonly', 'ref', 'return', 'sealed', 'sizeof', 'stackalloc',
                'static', 'struct', 'switch', 'this', 'throw', 'true', 'try',
                'typeof', 'unchecked', 'unsafe', 'using', 'virtual', 'volatile',
                'while', 'var', 'async', 'await', 'yield', 'get', 'set', 'value',
                'partial', 'where', 'nameof',
            ],
            'types': [
                'bool', 'byte', 'sbyte', 'char', 'decimal', 'double', 'float',
                'int', 'uint', 'long', 'ulong', 'short', 'ushort', 'object',
                'string', 'void', 'dynamic', 'nint', 'nuint',
                'String', 'Int32', 'Int64', 'Boolean', 'Object', 'List', 'Dictionary',
            ],
            'patterns': [
                (r'^\s*#\s*\w+', '#9876AA'),   # #region / #if 等のディレクティブ
                (r'\[[A-Za-z_]\w*(?:\([^)]*\))?\]', '#BBB529'),  # 属性 [Serializable] 等
            ],
            'strings': [r'@?"(?:[^"\\]|\\.)*"', r"'(?:[^'\\]|\\.)*'"],
            'comment': r'//[^\n]*',
            'block_comment': ('/*', '*/'),
        },
        'vb': {
            # VB6 / VBA / VB.NET 共通の主要キーワード (大文字小文字は区別しない)。
            'keywords': [
                'AddHandler', 'AddressOf', 'Alias', 'And', 'AndAlso', 'As', 'Boolean',
                'ByRef', 'ByVal', 'Call', 'Case', 'Catch', 'Class', 'Const', 'Continue',
                'Declare', 'Default', 'Delegate', 'Dim', 'DirectCast', 'Do', 'Each',
                'Else', 'ElseIf', 'End', 'EndIf', 'Enum', 'Erase', 'Error', 'Event',
                'Exit', 'False', 'Finally', 'For', 'Friend', 'Function', 'Get',
                'GetType', 'Global', 'GoSub', 'GoTo', 'Handles', 'If', 'Implements',
                'Imports', 'In', 'Inherits', 'Interface', 'Is', 'IsNot', 'Let',
                'Lib', 'Like', 'Loop', 'Me', 'Mod', 'Module', 'MustInherit',
                'MustOverride', 'MyBase', 'MyClass', 'Namespace', 'Narrowing', 'New',
                'Next', 'Not', 'Nothing', 'NotInheritable', 'NotOverridable',
                'Of', 'On', 'Operator', 'Option', 'Optional', 'Or', 'OrElse',
                'Overloads', 'Overridable', 'Overrides', 'ParamArray', 'Partial',
                'Preserve', 'Private', 'Property', 'Protected', 'Public', 'RaiseEvent',
                'ReadOnly', 'ReDim', 'REM', 'RemoveHandler', 'Resume', 'Return',
                'Select', 'Set', 'Shadows', 'Shared', 'Static', 'Step', 'Stop',
                'Sub', 'SyncLock', 'Then', 'Throw', 'To', 'True', 'Try', 'TypeOf',
                'Until', 'Using', 'Wend', 'When', 'While', 'Widening', 'With',
                'WithEvents', 'WriteOnly', 'Xor',
            ],
            'types': [
                'Boolean', 'Byte', 'SByte', 'Char', 'Date', 'Decimal', 'Double',
                'Integer', 'Long', 'Object', 'Short', 'Single', 'String', 'UInteger',
                'ULong', 'UShort', 'Variant', 'Currency',
            ],
            'patterns': [
                (r'^\s*#\s*\w+', '#9876AA'),                # #If / #Region 等のディレクティブ
                (r'<[A-Za-z_]\w*(?:\([^)]*\))?>', '#BBB529'),  # 属性 <Serializable> 等
                # Rem キーワードから始まる行コメントは行全体を comment 色で塗る
                (r'(?i)^\s*Rem\b.*$', '#808080'),
            ],
            # シングルクォートは VB ではコメントなので、文字列は二重引用符のみ。
            # VB の文字列内では "" が " のエスケープになるが、概ね "[^"]*" で
            # 視認上は十分 (誤検出は許容)。
            'strings': [r'"(?:[^"]|"")*"'],
            # シングルクォート始まり → 行末までコメント
            'comment': r"'[^\n]*",
            'kw_case_insensitive': True,
        },
        'xml': {
            # タグ・属性ベース (キーワードは持たない)
            'patterns': [
                (r'</?[A-Za-z_][\w:.\-]*', '#569CD6'),     # 開始/終了タグ名
                (r'/?>', '#569CD6'),                        # 閉じ > / />
                (r'[A-Za-z_][\w:.\-]*(?=\s*=)', '#9CDCFE'),  # 属性名
                (r'&[A-Za-z#0-9]+;', '#D7BA7D'),            # エンティティ参照
                (r'<[!?][\w\-]+', '#9876AA'),               # <?xml / <!DOCTYPE 等
            ],
            'strings': [r'"[^"]*"', r"'[^']*'"],
            'block_comment': ('<!--', '-->'),
        },
    }

    # ブロックコメント中を示すブロック状態値
    _STATE_BLOCK_COMMENT = 1

    # ログモード中のSQL検出パターン
    _SQL_INDICATOR = re.compile(
        r'\b(?:SELECT|INSERT\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM|'
        r'CREATE\s+(?:TABLE|INDEX|VIEW|DATABASE|SCHEMA)|'
        r'ALTER\s+TABLE|DROP\s+(?:TABLE|INDEX|VIEW)|'
        r'WITH\s+\w+\s+AS|MERGE\s+INTO|TRUNCATE\s+TABLE)\b',
        re.IGNORECASE,
    )
    _SQL_KEYWORDS_RE = re.compile(
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
    _SQL_STRING_RE = re.compile(r"'(?:[^'\\]|\\.|'')*'")
    _SQL_NUMBER_RE = re.compile(r'\b\d+(?:\.\d+)?\b')
    _SQL_COMMENT_RE = re.compile(r'--[^\n]*')

    def __init__(self, document, language='text'):
        super().__init__(document)
        self.language = language
        self._rules = []
        self._comment_fmt = None
        self._block_comment_spec = None
        self._line_level_rules = []   # log 用：行全体の色
        self._build_rules()

    def _fmt(self, color, bold=False, italic=False):
        f = QTextCharFormat()
        f.setForeground(QColor(color))
        if bold:
            f.setFontWeight(700)
        if italic:
            f.setFontItalic(True)
        return f

    def _build_rules(self):
        self._rules.clear()
        self._line_level_rules.clear()
        self._pal = _syntax_palette()   # テーマ明暗に応じたトークン配色
        self._comment_fmt = self._fmt(self._pal['comment'], italic=True)
        self._block_comment_spec = None

        spec = self.LANG_RULES.get(self.language)
        if not spec:
            return

        ci = spec.get('kw_case_insensitive', False)
        re_opts = (QRegularExpression.PatternOption.CaseInsensitiveOption
                   if ci else QRegularExpression.PatternOption(0))

        # --- log 専用：行全体レベル色 ---
        for pat_str, bg, fg in spec.get('line_levels', []):
            fmt = QTextCharFormat()
            if bg:
                fmt.setBackground(QColor(bg))
            if fg:
                fmt.setForeground(QColor(fg))
            self._line_level_rules.append((re.compile(pat_str, re.IGNORECASE), fmt))

        # --- log 専用：行内インラインパターン ---
        for pat_str, color in spec.get('inline', []):
            self._rules.append((QRegularExpression(pat_str), self._fmt(color)))

        # --- 汎用パターン (プリプロセッサ / XMLタグ等) ---
        # キーワード等より先に追加 → 後段の文字列・コメントで上書きされる
        for pat_str, color in spec.get('patterns', []):
            self._rules.append((QRegularExpression(pat_str), self._fmt(color)))

        # --- 通常言語ルール ---
        # 注: 後から append したルールが先のルールを上書きするため、
        #     優先度の低いもの (数値) から順に追加し、文字列・コメントを最後に置く。
        # キーワード（橙・太字）
        kw_fmt = self._fmt(self._pal['keyword'], bold=True)
        for kw in spec.get('keywords', []):
            pat = QRegularExpression(r'\b' + kw + r'\b', re_opts)
            self._rules.append((pat, kw_fmt))

        # データ型（水色）
        type_fmt = self._fmt(self._pal['type'], bold=True)
        for t in spec.get('types', []):
            pat = QRegularExpression(r'\b' + t + r'\b', re_opts)
            self._rules.append((pat, type_fmt))

        # 組み込み関数（黄緑）
        fn_fmt = self._fmt(self._pal['function'])
        for fn in spec.get('functions', []):
            pat = QRegularExpression(r'\b' + fn + r'\b', re_opts)
            self._rules.append((pat, fn_fmt))

        # 数値（青）— ※先に追加して、後段の文字列ルールで上書きされるようにする
        # （文字列リテラル内 '#2b2b2b' の数字に青色が乗らないため）
        if 'line_levels' not in spec:
            self._rules.append((QRegularExpression(r'\b\d+\.?\d*\b'), self._fmt(self._pal['number'])))

        # 文字列リテラル（緑）— 数値より後に追加 → 文字列が数値を上書き
        str_fmt = self._fmt(self._pal['string'])
        for pat in spec.get('strings', []):
            self._rules.append((QRegularExpression(pat), str_fmt))

        # 単行コメント — 文字列より後 → コメントが最優先
        if 'comment' in spec:
            self._rules.append((QRegularExpression(spec['comment']), self._comment_fmt))

        # ブロックコメントは highlightBlock で状態管理するため別保持
        if 'block_comment' in spec:
            self._block_comment_spec = spec['block_comment']

    def highlightBlock(self, text):
        # log：行全体をレベル色で塗る（最初にマッチしたレベルのみ）
        for pat, fmt in self._line_level_rules:
            if pat.search(text):
                self.setFormat(0, len(text), fmt)
                break

        # ブロックコメント処理（/* ... */ / multiline対応）
        non_comment_ranges = self._apply_block_comments(text)

        # 通常ルール・インラインルール（コメント外の範囲のみ）
        for pattern, fmt in self._rules:
            it = pattern.globalMatch(text)
            while it.hasNext():
                m = it.next()
                s, length = m.capturedStart(), m.capturedLength()
                e = s + length
                if any(ns <= s and e <= ne for ns, ne in non_comment_ranges):
                    self.setFormat(s, length, fmt)

        # log モード時、行内に SQL 指標があれば SQL 構文も上書き色分け
        if self.language == 'log' and self._SQL_INDICATOR.search(text):
            self._apply_sql_inline(text)

    def _apply_sql_inline(self, text: str):
        """log 中の SQL 行に対し、SQL キーワード等を着色"""
        pal = getattr(self, '_pal', None) or _syntax_palette()
        kw_fmt = self._fmt(pal['keyword'], bold=True)
        for m in self._SQL_KEYWORDS_RE.finditer(text):
            self.setFormat(m.start(), m.end() - m.start(), kw_fmt)
        num_fmt = self._fmt(pal['number'])
        for m in self._SQL_NUMBER_RE.finditer(text):
            self.setFormat(m.start(), m.end() - m.start(), num_fmt)
        str_fmt = self._fmt(pal['string'])
        for m in self._SQL_STRING_RE.finditer(text):
            self.setFormat(m.start(), m.end() - m.start(), str_fmt)
        cm_fmt = self._fmt(pal['comment'], italic=True)
        for m in self._SQL_COMMENT_RE.finditer(text):
            self.setFormat(m.start(), m.end() - m.start(), cm_fmt)

    def _apply_block_comments(self, text) -> list[tuple[int, int]]:
        """ブロックコメントを着色し、コメント外の区間リストを返す"""
        if not self._block_comment_spec:
            self.setCurrentBlockState(0)
            return [(0, len(text))]

        start_str, end_str = self._block_comment_spec
        in_comment = (self.previousBlockState() == self._STATE_BLOCK_COMMENT)
        pos = 0
        seg_start = 0
        non_comment: list[tuple[int, int]] = []

        while pos <= len(text):
            if in_comment:
                end_idx = text.find(end_str, pos)
                if end_idx == -1:
                    self.setFormat(seg_start, len(text) - seg_start, self._comment_fmt)
                    self.setCurrentBlockState(self._STATE_BLOCK_COMMENT)
                    return non_comment
                end_pos = end_idx + len(end_str)
                self.setFormat(seg_start, end_pos - seg_start, self._comment_fmt)
                in_comment = False
                pos = end_pos
                seg_start = pos
            else:
                start_idx = text.find(start_str, pos)
                if start_idx == -1:
                    non_comment.append((seg_start, len(text)))
                    break
                non_comment.append((seg_start, start_idx))
                in_comment = True
                seg_start = start_idx
                pos = start_idx + len(start_str)

        self.setCurrentBlockState(self._STATE_BLOCK_COMMENT if in_comment else 0)
        return non_comment

    def set_language(self, lang):
        self.language = lang
        self._build_rules()
        self.rehighlight()

    def rebuild_theme(self):
        """テーマ変更時に配色を作り直して再ハイライト。"""
        self._build_rules()
        self.rehighlight()


# ---------------------------------------------------------------------------
# インライン検索バー（エディタ下部に埋め込み）
# ---------------------------------------------------------------------------

class InlineSearchBar(QWidget):
    _MAX_HISTORY = 20

    def __init__(self, editor: 'CodeEditor', parent=None):
        super().__init__(parent)
        self._editor = editor
        # 「全文スキャンしてもマッチなし」と判明したパターンをキャッシュ。
        # 大ファイルで連打したとき何度も全スキャンしないようにする。
        # _on_input_changed (= 検索テキスト変化) でクリア。
        self._no_match_text: str | None = None
        # ▲▼ 連打対策: find 処理中は新クリックを無視 (single-flight)。
        # 連打が main thread のイベントキューに積まれて「応答なし」を
        # 起こすのを防ぐ。リリースは次イベントループで行う (deferred)。
        self._busy_find = False
        self._build_ui()
        self._load_persistent_history()
        self.hide()

    def _load_persistent_history(self):
        """グローバル SEARCH_HISTORY からコンボに復元 (新しい順)"""
        for item in SEARCH_HISTORY.get('search', []):
            if self.search_input.findText(item) < 0:
                self.search_input.addItem(item)
        for item in SEARCH_HISTORY.get('replace', []):
            if self.replace_input.findText(item) < 0:
                self.replace_input.addItem(item)
        # 復元したばかりの履歴で検索欄を埋めないよう、現在テキストをクリア
        self.search_input.setCurrentText('')
        self.replace_input.setCurrentText('')

    # ------------------------------------------------------------------ UI

    def _build_ui(self):
        layout = QHBoxLayout()
        layout.setContentsMargins(6, 3, 6, 3)
        layout.setSpacing(4)

        # --- 検索行 (🔍 [input] [📜] [▲] [▼] [matches]  [Aa] [.*]  ✕) ---
        layout.addWidget(QLabel("🔍"))
        self.search_input = QComboBox()
        self.search_input.setEditable(True)
        self.search_input.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.search_input.lineEdit().setPlaceholderText(
            "検索パターン (Enter: 次 / Shift+Enter: 前)"
        )
        self.search_input.setMinimumWidth(220)
        self.search_input.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        layout.addWidget(self.search_input, 2)

        self.search_hist_btn = QPushButton("📜")
        self.search_hist_btn.setFixedWidth(26)
        self.search_hist_btn.setToolTip("検索履歴を開く")
        self.search_hist_btn.clicked.connect(self.search_input.showPopup)
        layout.addWidget(self.search_hist_btn)

        self.prev_btn = QPushButton("▲")
        self.prev_btn.setFixedWidth(26)
        self.prev_btn.setToolTip("前を検索 (Shift+Enter)")
        self.next_btn = QPushButton("▼")
        self.next_btn.setFixedWidth(26)
        self.next_btn.setToolTip("次を検索 (Enter)")
        layout.addWidget(self.prev_btn)
        layout.addWidget(self.next_btn)

        self.match_label = QLabel("")
        self.match_label.setMinimumWidth(80)
        self.match_label.setStyleSheet("color:#9ED969; font-size:10px; padding-left:4px;")
        layout.addWidget(self.match_label)

        # 置換セクション区切り (置換非表示時はこのセパレータも隠す)
        self._replace_sep_before = self._sep()
        layout.addWidget(self._replace_sep_before)

        # --- 置換欄 ---
        layout.addWidget(QLabel("↦"))   # 「マップ to」 を意味する記号 — 置換セクションの目印
        self._replace_arrow_label = layout.itemAt(layout.count() - 1).widget()

        self.replace_input = QComboBox()
        self.replace_input.setEditable(True)
        self.replace_input.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.replace_input.lineEdit().setPlaceholderText("置換後のテキスト")
        self.replace_input.setMinimumWidth(160)
        self.replace_input.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        layout.addWidget(self.replace_input, 1)

        self._replace_hist_btn = QPushButton("📜")
        self._replace_hist_btn.setFixedWidth(26)
        self._replace_hist_btn.setToolTip("置換履歴を開く")
        self._replace_hist_btn.clicked.connect(self.replace_input.showPopup)
        layout.addWidget(self._replace_hist_btn)

        self.replace_btn = QPushButton("置換")
        self.replace_btn.setFixedWidth(48)
        self.replace_btn.setToolTip("現在のマッチを置換")
        self.replace_all_btn = QPushButton("全置換")
        self.replace_all_btn.setFixedWidth(56)
        self.replace_all_btn.setToolTip("全マッチを一括置換")
        layout.addWidget(self.replace_btn)
        layout.addWidget(self.replace_all_btn)

        self._replace_sep_after = self._sep()
        layout.addWidget(self._replace_sep_after)

        # 置換セクションの子ウィジェット一覧 (set_replace_visible で一括表示切替)
        self._replace_widgets = [
            self._replace_sep_before, self._replace_arrow_label,
            self.replace_input, self._replace_hist_btn,
            self.replace_btn, self.replace_all_btn, self._replace_sep_after,
        ]

        # --- オプションをトグルボタン化 (Grepパネルと統一) ---
        self.case_check = QPushButton("Aa")
        self.case_check.setCheckable(True)
        self.case_check.setFixedWidth(34)
        self.case_check.setToolTip("大文字小文字を区別")
        self.regex_check = QPushButton(".*")
        self.regex_check.setCheckable(True)
        self.regex_check.setFixedWidth(34)
        self.regex_check.setToolTip("正規表現として扱う")
        layout.addWidget(self.case_check)
        layout.addWidget(self.regex_check)

        layout.addStretch()

        # --- 閉じる ---
        self.close_btn = QPushButton("✕")
        self.close_btn.setFixedWidth(28)
        self.close_btn.setToolTip("検索バーを閉じる (Esc)")
        layout.addWidget(self.close_btn)

        self.setLayout(layout)
        # 全体スタイル (背景・コンボのみ)
        self._apply_style()

        # デバウンスタイマー: タイプ後 N ms 経過してから検索実行
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.timeout.connect(self._update_highlights)

        # シグナル
        self.search_input.lineEdit().textChanged.connect(self._on_input_changed)
        self.search_input.lineEdit().returnPressed.connect(self._on_return)
        self.search_input.currentIndexChanged.connect(
            lambda _: self._update_highlights()   # 履歴選択は即時
        )
        self.case_check.toggled.connect(self._update_highlights)
        self.regex_check.toggled.connect(self._update_highlights)
        self.next_btn.clicked.connect(self.find_next)
        self.prev_btn.clicked.connect(self.find_prev)
        self.replace_btn.clicked.connect(self.replace_current)
        self.replace_all_btn.clicked.connect(self.replace_all)
        self.close_btn.clicked.connect(self.close_bar)

    def _apply_style(self):
        """検索バーのスタイルをテーマ + UIフォントサイズ連動で適用。"""
        fs = SETTINGS.get('ui_font_size', 10)
        t = _theme()
        # Light 系テーマでは border 色 (#cccccc 等) が背景と同化しがちなので、
        # より濃い text_dim を使って入力欄/ボタンの境界をはっきり見せる。
        is_light = SETTINGS.get('theme', 'Dark') in ('Light', 'Solarized Light')
        edge = t['text_dim'] if is_light else t['border']
        # Light テーマでは編集エリア (白) と toolbar_bg (#e6e6e6) の差が小さく
        # 「検索バーが見えない」ので、専用の青みがかった背景に置き換える。
        bar_bg = '#d8e2f0' if is_light else t['toolbar_bg']
        # objectName 経由でこの InlineSearchBar 自身にだけボーダーを適用
        self.setObjectName('InlineSearchBar')
        self.setStyleSheet(f"""
            QWidget   {{ background: {bar_bg}; }}
            #InlineSearchBar {{ border-top:1px solid {edge};
                               border-bottom:1px solid {edge}; }}
            QLabel    {{ color: {t['text']}; }}
            QComboBox {{ background:{t['panel_bg']}; color:{t['text']};
                        border:1px solid {edge};
                        padding:2px 4px; border-radius:3px; font-size:{fs}px; }}
            QComboBox:focus {{ border:1px solid {t['selection']}; }}
            QComboBox QAbstractItemView {{ background:{t['panel_bg']}; color:{t['text']};
                                          selection-background-color:{t['selection']}; }}
        """)
        # ボタン群をテーマ連動で再スタイル
        btn_style = (
            f"QPushButton {{ background:{t['control_bg']}; color:{t['text']};"
            f"              border:1px solid {edge};"
            f"              padding:2px 4px; border-radius:3px; }}"
            f"QPushButton:hover {{ background:{t['control_hover']}; }}"
        )
        toggle_style = (
            f"QPushButton {{ background:{t['control_bg']}; color:{t['text']};"
            f"              border:1px solid {edge};"
            f"              padding:2px 4px; border-radius:3px; font-weight:600; }}"
            f"QPushButton:hover {{ background:{t['control_hover']}; }}"
            f"QPushButton:checked {{ background:{t['selection']}; color:{t['text']};"
            f"              border:1px solid {t['selection']}; }}"
        )
        close_style = (
            f"QPushButton {{ background:{t['control_bg']}; color:{t['text']};"
            f"              border:1px solid {edge};"
            f"              padding:2px 4px; border-radius:3px; font-weight:600; }}"
            f"QPushButton:hover {{ background:#c0392b; color:#fff; border:1px solid #e05545; }}"
        )
        green_style = (
            "QPushButton { background:#3a6e3a; color:#e0f0e0; border:none;"
            "              padding:3px 8px; border-radius:3px; font-weight:600; }"
            "QPushButton:hover { background:#4a8e4a; }"
        )
        for b in (self.search_hist_btn, self.prev_btn, self.next_btn,
                  self._replace_hist_btn, self.replace_btn):
            b.setStyleSheet(btn_style)
        self.replace_all_btn.setStyleSheet(green_style)
        self.case_check.setStyleSheet(toggle_style)
        self.regex_check.setStyleSheet(toggle_style)
        self.close_btn.setStyleSheet(close_style)
        # フォントが大きい時に入力欄が潰れないよう高さ上限も連動
        self.setMaximumHeight(max(36, fs + 22))

    def apply_ui_settings(self):
        """UIフォントサイズ等の設定変更を反映 (MainWindow から呼ばれる)。"""
        self._apply_style()

    def _on_input_changed(self, text):
        """入力中はタイマー再起動。ドキュメントサイズに応じて遅延を調整。"""
        # 検索テキスト変化 → 「マッチなし」キャッシュを無効化
        self._no_match_text = None
        if not text:
            self._debounce_timer.stop()
            self._editor.set_search_highlights([])
            self.match_label.setText("")
            return
        # ドキュメントサイズで遅延を変える (重い処理を頻発させない)
        doc_size = self._editor.document().characterCount()
        if doc_size < 100_000:           # 〜100KB
            delay = 100
        elif doc_size < 2_000_000:        # 〜2MB
            delay = 300
        elif doc_size < 10_000_000:       # 〜10MB
            delay = 700
        else:                              # 10MB超
            delay = 1200
        self._debounce_timer.start(delay)
        self.match_label.setText("…")
        self.match_label.setStyleSheet("color:#808080; font-size:10px;")

    @staticmethod
    def _sep():
        f = QFrame()
        f.setFrameShape(QFrame.Shape.VLine)
        f.setStyleSheet("color:#555;")
        return f

    # ---------------------------------------------------------------- 履歴

    def _push_history(self, combo: QComboBox, text: str):
        if not text:
            return
        # ▲▼ 連打時の最適化: 既に履歴トップなら何もしない (disk write 抑止、
        # currentIndexChanged → _update_highlights のチェーンも回避)
        if combo.count() > 0 and combo.itemText(0) == text:
            return
        idx = combo.findText(text)
        if idx >= 0:
            combo.removeItem(idx)
        combo.insertItem(0, text)
        combo.setCurrentIndex(0)
        while combo.count() > self._MAX_HISTORY:
            combo.removeItem(combo.count() - 1)
        # グローバル履歴に反映してファイルに永続化
        key = 'search' if combo is self.search_input else 'replace'
        items = [combo.itemText(i) for i in range(combo.count())]
        SEARCH_HISTORY[key] = items[:_HISTORY_MAX]
        _save_search_history()

    # --------------------------------------------------------------- 公開

    def show_bar(self, initial_text: str = None, show_replace: bool = False):
        """初期テキスト指定可。指定があれば検索欄に挿入してハイライト即実行。
        show_replace: True で置換欄も表示 (Ctrl+H), False で検索のみ (Ctrl+F)。
        """
        self.show()
        self.set_replace_visible(show_replace)
        if initial_text:
            self.search_input.setCurrentText(initial_text)
        self.search_input.lineEdit().setFocus()
        self.search_input.lineEdit().selectAll()
        self._update_highlights()

    def set_replace_visible(self, visible: bool):
        """置換欄 (replace input / hist / 置換 / 全置換ボタン / セパレータ) の表示切替。"""
        for w in self._replace_widgets:
            w.setVisible(visible)

    def close_bar(self):
        self._editor.set_search_highlights([])
        self.hide()
        self._editor.setFocus()

    # -------------------------------------------------------------- イベント

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close_bar()
        else:
            super().keyPressEvent(event)

    def _on_return(self):
        # Enter 確定時のみ履歴に push (▲▼ ボタンクリックでは push しない)
        self._push_history(self.search_input, self._search_text())
        mods = QApplication.keyboardModifiers()
        if mods & Qt.KeyboardModifier.ShiftModifier:
            self.find_prev()
        else:
            self.find_next()

    # ---------------------------------------------------------- ハイライト

    def _search_text(self) -> str:
        return self.search_input.currentText()

    def _replace_text(self) -> str:
        return self.replace_input.currentText()

    # 巨大ファイルでハイライト数を制限 (描画コスト抑止)
    _MAX_HIGHLIGHTS = 5000
    # 全マッチハイライト処理自体を諦めるドキュメントサイズしきい値 (5MB)
    # ▲▼ ナビゲーションは Qt 内蔵 find() で個別マッチに移動できるため、
    # 全マッチハイライトをスキップしても検索自体は機能する。
    _NO_HIGHLIGHT_DOC_CHARS = 5_000_000

    def _update_highlights(self):
        text = self._search_text()
        if not text:
            self._editor.set_search_highlights([])
            self.match_label.setText("")
            return
        try:
            flags = 0 if self.case_check.isChecked() else re.IGNORECASE
            pat = re.compile(
                text if self.regex_check.isChecked() else re.escape(text), flags
            )
        except re.error:
            self.match_label.setText("正規表現エラー")
            self.match_label.setStyleSheet("color:#FF7070; font-size:10px;")
            return

        doc = self._editor.document()
        # 5MB 超は全マッチ走査 + ExtraSelection 生成が秒オーダーで重くなり、
        # その間に ▲▼ も詰まるためハイライトはスキップして ▲▼ 検索のみ有効化
        if doc.characterCount() > self._NO_HIGHLIGHT_DOC_CHARS:
            self._editor.set_search_highlights([])
            self.match_label.setText("着色省略 (大ファイル)")
            self.match_label.setToolTip(
                "大ファイル (5MB 超) のため全マッチの黄色着色を省略しています。\n"
                "▲▼ ボタンで個別のマッチへ移動してください。"
            )
            self.match_label.setStyleSheet("color:#888; font-size:10px;")
            return
        # 通常モードに戻ったら tooltip もクリア
        self.match_label.setToolTip("")

        doc_text = doc.toPlainText()

        # ハイライトは MAX_HIGHLIGHTS まで、件数は最後までカウント
        # 鮮やかな黄背景 + 黒文字 + 太字 で視認性最大化 (テーマ問わず目立つ)
        fmt = QTextCharFormat()
        fmt.setBackground(QColor("#FFEB3B"))
        fmt.setForeground(QColor("#000000"))
        fmt.setFontWeight(700)
        selections = []
        total = 0
        for m in pat.finditer(doc_text):
            total += 1
            if len(selections) < self._MAX_HIGHLIGHTS:
                sel = QTextEdit.ExtraSelection()
                sel.format = fmt
                cur = self._editor.textCursor()
                cur.setPosition(m.start())
                cur.setPosition(m.end(), cur.MoveMode.KeepAnchor)
                sel.cursor = cur
                selections.append(sel)

        if total == 0:
            self._editor.set_search_highlights([])
            self.match_label.setText("見つからない")
            self.match_label.setStyleSheet("color:#FF7070; font-size:10px;")
            return

        self._editor.set_search_highlights(selections)
        if total > self._MAX_HIGHLIGHTS:
            self.match_label.setText(f"{total} 件 (上位{self._MAX_HIGHLIGHTS}件のみ着色)")
        else:
            self.match_label.setText(f"{total} 件")
        self.match_label.setStyleSheet("color:#6A8759; font-size:10px;")

    # ---------------------------------------------------------- ナビゲーション

    def _find_flags(self):
        f = QTextDocument.FindFlag(0)
        if self.case_check.isChecked():
            f |= QTextDocument.FindFlag.FindCaseSensitively
        return f

    def _do_find(self, backward: bool = False):
        text = self._search_text()
        if not text:
            return
        # 大ファイルで「マッチなし」をキャッシュ済みなら、再 find せず即通知
        # (前回 2 回の全文 find で確認済み = 改めて scan する意味がない)
        if self._no_match_text == text:
            self._show_banner(
                f"⚠  「{text}」 にマッチする箇所が見つかりません",
                bg="#E74C3C", fg="#ffffff",
            )
            self._push_status_msg(f"検索: 「{text}」 にマッチなし")
            return
        flags = self._find_flags()
        if backward:
            flags |= QTextDocument.FindFlag.FindBackward

        wrapped = False
        if self.regex_check.isChecked():
            pat = QRegularExpression(text)
            if not self.case_check.isChecked():
                pat.setPatternOptions(QRegularExpression.PatternOption.CaseInsensitiveOption)
            found = self._editor.find(pat, flags)
            if not found:
                cur = self._editor.textCursor()
                cur.movePosition(cur.MoveOperation.End if backward else cur.MoveOperation.Start)
                self._editor.setTextCursor(cur)
                wrapped = self._editor.find(pat, flags)
        else:
            found = self._editor.find(text, flags)
            if not found:
                cur = self._editor.textCursor()
                cur.movePosition(cur.MoveOperation.End if backward else cur.MoveOperation.Start)
                self._editor.setTextCursor(cur)
                wrapped = self._editor.find(text, flags)
        # マッチ後のカーソル後処理:
        # 1) zero-width マッチ (lookahead only 等) は 1 文字ずつしか進まないため
        #    現在行末尾までカーソルを進めて「次のマッチは別の行から」になる
        # 2) 通常マッチで「行全体を消費する regex」 (`^(?=.*X).+` 等) では
        #    カーソルが行全体を選択 → Qt の selection color が行全体を脱色する。
        #    選択を解除 (selectionEnd に position をたためる) して、
        #    テキスト本来の syntax 色を維持する。
        if (found or wrapped):
            cur = self._editor.textCursor()
            if cur.position() == cur.anchor():
                # zero-width: 行末/行頭へ動かす
                if backward:
                    cur.movePosition(cur.MoveOperation.StartOfBlock)
                else:
                    cur.movePosition(cur.MoveOperation.EndOfBlock)
                self._editor.setTextCursor(cur)
            else:
                # 通常マッチ: 選択を解除して脱色を防ぐ。位置は match の終端
                # (forward なら selectionEnd / backward なら selectionStart)
                # に置き、次回 find の起点として正しく機能させる。
                end_pos = cur.selectionStart() if backward else cur.selectionEnd()
                cur.setPosition(end_pos)
                self._editor.setTextCursor(cur)
        # スクロール (= layout 計算) は main thread を解放するため deferred 実行。
        # 連打 → 古いクリックの scroll は最新クリック後にまとめて適用される
        # (どうせ最新のカーソル位置に飛ばすので問題なし)。
        doc_size = self._editor.document().characterCount()
        editor = self._editor
        if doc_size < 1_000_000:
            QTimer.singleShot(0, editor.centerCursor)
        else:
            QTimer.singleShot(0, editor.ensureCursorVisible)
        # フィードバックを statusBar (= 主) + banner (= 補助) で出す:
        # - 通常マッチ (found=True): 何も出さない
        # - ラップ発生  (wrapped=True): 「上下端で折返し」 (橙)
        # - 全くマッチなし (両方False): 「マッチなし」 (赤) + キャッシュ
        if wrapped:
            if backward:
                msg = "⤴ ファイルの先頭に到達 — 末尾から検索を継続"
            else:
                msg = "⤵ ファイルの末尾に到達 — 先頭から検索を継続"
            self._push_status_msg(msg, bg="#FFB454", fg="#1a1a1a")
            self._show_banner(msg, bg="#FFB454", fg="#1a1a1a")
            self._no_match_text = None   # 見つかってる = キャッシュ無効
        elif not found:
            # 全文中マッチゼロ → キャッシュして次回以降即終了
            self._no_match_text = text
            msg = f"⚠ 「{text}」 にマッチする箇所が見つかりません"
            self._push_status_msg(msg, bg="#E74C3C", fg="#ffffff")
            self._show_banner(msg, bg="#E74C3C", fg="#ffffff")
        else:
            # 通常ヒット → キャッシュは無効化 (テキスト変化時にも消すが念のため)
            self._no_match_text = None

    def _push_status_msg(self, msg: str, duration_ms: int = 3000,
                         bg: str = "#FFB454", fg: str = "#1a1a1a"):
        """メインウィンドウの statusBar に色付き通知を出す (常に最下部に
        必ず表示される。banner overlay は z-order トラブル時に隠れることが
        あるため、こちらを通知の主チャネルとする)。"""
        try:
            sb = self._editor.window().statusBar()
            if sb is None:
                return
            sb.setStyleSheet(
                f"QStatusBar {{ background:{bg}; color:{fg};"
                f" font-weight:700; padding:3px 10px; font-size:12px; }}"
            )
            sb.showMessage(msg, duration_ms)
            # スタイルだけは duration 後に剥がす (messageTimeout だけだと
            # 背景色が残ったままになる)
            QTimer.singleShot(duration_ms, lambda: sb.setStyleSheet(""))
        except Exception:
            pass

    def _show_banner(self, msg: str, *,
                     bg: str = "#FFB454",
                     fg: str = "#1a1a1a",
                     duration_ms: int = 2500):
        """エディタ上部に大きめのオーバーレイ帯バナーを表示。
        viewport の子にして paint cycle で隠れないようにする。"""
        if not hasattr(self, '_banner'):
            from PyQt6.QtCore import Qt as _Qt
            # 親は viewport: 標準のテキスト paint と z-order で競合せず、
            # raise_() で確実に最前面に出せる
            self._banner = QLabel(self._editor.viewport())
            self._banner.setAlignment(_Qt.AlignmentFlag.AlignCenter)
            self._banner.setAttribute(_Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            self._banner.hide()
            self._banner_timer = QTimer(self)
            self._banner_timer.setSingleShot(True)
            self._banner_timer.timeout.connect(self._banner.hide)
            # エディタ viewport リサイズに追従して帯を再センタリング
            self._editor.viewport().installEventFilter(self)

        self._banner.setText("  " + msg + "  ")
        self._banner.setStyleSheet(
            f"background:{bg}; color:{fg};"
            f" padding:10px 24px; font-size:13px; font-weight:700;"
            f" border-radius:6px; border:1px solid rgba(0,0,0,0.25);"
        )
        self._reposition_banner()
        self._banner.show()
        self._banner.raise_()
        # 即時 paint を強制 (連打 / 大ファイルでイベント詰まり時に効く)
        self._banner.repaint()
        self._banner_timer.start(duration_ms)

    def _reposition_banner(self):
        """帯を viewport の上端中央に配置。"""
        if not hasattr(self, '_banner'):
            return
        self._banner.adjustSize()
        w = self._banner.width()
        vp = self._editor.viewport()
        vp_w = vp.width() if vp.width() > 0 else self._editor.width()
        x = max(0, (vp_w - w) // 2)
        self._banner.move(x, 12)

    def eventFilter(self, obj, event):
        # viewport リサイズ時に帯のセンタリングを維持
        if (hasattr(self, '_banner')
                and obj is self._editor.viewport()):
            try:
                from PyQt6.QtCore import QEvent
                if event.type() == QEvent.Type.Resize:
                    self._reposition_banner()
            except Exception:
                pass
        return super().eventFilter(obj, event)

    def _flash_status(self, msg: str, color: str = "#FFB454", duration_ms: int = 2500):
        """検索結果ラベルに一時メッセージを表示。
        - color: メッセージの文字色 (上下端到達は橙 / マッチなしは赤)
        - duration_ms: 表示時間 (デフォルト 2.5 秒)
        終了後は元のテキスト/スタイルに戻す。"""
        prev_text = self.match_label.text()
        prev_style = self.match_label.styleSheet()
        self.match_label.setText(msg)
        self.match_label.setStyleSheet(
            f"color:{color}; font-size:10px; font-weight:600;"
        )

        def _restore():
            # 直前 text/style に戻す (フラッシュ中に他の更新が無ければ)
            try:
                self.match_label.setText(prev_text)
                self.match_label.setStyleSheet(prev_style)
            except Exception:
                pass
        QTimer.singleShot(duration_ms, _restore)

    def find_next(self):
        if self._busy_find:
            return
        self._busy_find = True
        try:
            # _push_history はボタンクリック毎に呼ぶ必要ない (履歴トップ
            # に同じテキストなら no-op だが、disk I/O などのオーバーヘッド
            # 抑制のため Enter 確定時にのみ push する設計に整理)。
            self._do_find(backward=False)
        finally:
            # 次イベントループでフラグ解除 — その間に積まれた連打クリックは
            # disabled 同等の扱いで取りこぼされ、UI が固まらない
            QTimer.singleShot(0, self._release_busy_find)

    def find_prev(self):
        if self._busy_find:
            return
        self._busy_find = True
        try:
            self._do_find(backward=True)
        finally:
            QTimer.singleShot(0, self._release_busy_find)

    def _release_busy_find(self):
        self._busy_find = False

    # ---------------------------------------------------------------- 置換

    def replace_current(self):
        self._push_history(self.search_input, self._search_text())
        self._push_history(self.replace_input, self._replace_text())
        cur = self._editor.textCursor()
        if cur.hasSelection():
            cur.insertText(self._replace_text())
        self.find_next()

    def replace_all(self):
        text = self._search_text()
        if not text:
            return
        self._push_history(self.search_input, text)
        self._push_history(self.replace_input, self._replace_text())
        cur = self._editor.textCursor()
        cur.movePosition(cur.MoveOperation.Start)
        self._editor.setTextCursor(cur)
        count = 0
        while self._editor.find(text, self._find_flags()):
            self._editor.textCursor().insertText(self._replace_text())
            count += 1
        self._update_highlights()
        self.match_label.setText(f"{count} 件置換")
        self.match_label.setStyleSheet("color:#6A8759; font-size:10px;")


# ---------------------------------------------------------------------------
# 検索・置換ダイアログ
# ---------------------------------------------------------------------------

class SearchDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("検索・置換")
        self.setMinimumWidth(420)

        layout = QVBoxLayout()
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        g = QGridLayout()
        g.addWidget(QLabel("検索:"), 0, 0)
        self.search_input = QLineEdit()
        g.addWidget(self.search_input, 0, 1)
        g.addWidget(QLabel("置換:"), 1, 0)
        self.replace_input = QLineEdit()
        g.addWidget(self.replace_input, 1, 1)
        layout.addLayout(g)

        self.case_check = QCheckBox("大文字小文字を区別する")
        layout.addWidget(self.case_check)

        btns = QHBoxLayout()
        self.find_btn = QPushButton("次を検索")
        self.replace_btn = QPushButton("置換")
        self.replace_all_btn = QPushButton("すべて置換")
        close_btn = QPushButton("閉じる")
        for b in (self.find_btn, self.replace_btn, self.replace_all_btn, close_btn):
            btns.addWidget(b)
        layout.addLayout(btns)

        self.status_label = QLabel("")
        layout.addWidget(self.status_label)
        self.setLayout(layout)

        close_btn.clicked.connect(self.close)
        self.find_btn.clicked.connect(self.find_next)
        self.replace_btn.clicked.connect(self.replace_current)
        self.replace_all_btn.clicked.connect(self.replace_all)

        self.search_input.returnPressed.connect(self.find_next)

    def _editor(self):
        p = self.parent()
        return p.current_editor() if p else None

    def _flags(self):
        flags = QTextDocument.FindFlag(0)
        if self.case_check.isChecked():
            flags |= QTextDocument.FindFlag.FindCaseSensitively
        return flags

    def find_next(self):
        editor = self._editor()
        text = self.search_input.text()
        if not editor or not text:
            return
        found = editor.find(text, self._flags())
        if not found:
            c = editor.textCursor()
            c.movePosition(c.MoveOperation.Start)
            editor.setTextCursor(c)
            found = editor.find(text, self._flags())
        self.status_label.setText("見つかりました" if found else "見つかりませんでした")

    def replace_current(self):
        editor = self._editor()
        if editor and editor.textCursor().hasSelection():
            editor.textCursor().insertText(self.replace_input.text())
        self.find_next()

    def replace_all(self):
        editor = self._editor()
        text = self.search_input.text()
        if not editor or not text:
            return
        c = editor.textCursor()
        c.movePosition(c.MoveOperation.Start)
        editor.setTextCursor(c)
        count = 0
        while editor.find(text, self._flags()):
            editor.textCursor().insertText(self.replace_input.text())
            count += 1
        self.status_label.setText(f"{count} 件置換しました")


# ---------------------------------------------------------------------------
# FTPプロファイル管理
# ---------------------------------------------------------------------------

PROFILES_PATH = os.path.join(os.path.expanduser('~'), '.text_editor_ftp_profiles.json')


def load_profiles() -> dict:
    if os.path.exists(PROFILES_PATH):
        try:
            with open(PROFILES_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_profiles(profiles: dict):
    with open(PROFILES_PATH, 'w', encoding='utf-8') as f:
        json.dump(profiles, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# FTPプロファイル管理ダイアログ (並べ替え/名前変更/削除)
# ---------------------------------------------------------------------------

class FTPProfileManagerDialog(QDialog):
    """FTP接続プロファイルの並べ替え/名前変更/削除を行うダイアログ。
    LogViewer のサーバープロファイル管理と同じ操作感。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("FTPプロファイル管理")
        self.setMinimumSize(420, 360)
        self._profiles = load_profiles()
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
            QListWidget::item:selected {{ background:{t['selection']}; }}
            QPushButton {{ background:{t['control_bg']}; color:{t['text']};
                          border:none; padding:4px 12px; border-radius:2px; }}
            QPushButton:hover {{ background:{t['control_hover']}; }}
            QPushButton:default {{ background:{t['selection']}; color:{t['text']}; }}
        """)

    def _populate(self):
        self.list.clear()
        for name, info in self._profiles.items():
            host = info.get('host', '')
            user = info.get('user', '')
            port = info.get('port', 21)
            item = QListWidgetItem(name)
            item.setToolTip(f"{user}@{host}:{port}")
            self.list.addItem(item)

    def _on_rename(self, item):
        old = item.text()
        new, ok = QInputDialog.getText(self, "名前変更", "新しい名前:", text=old)
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
            self, "削除確認", f"FTPプロファイル「{name}」を削除しますか？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        self._profiles.pop(name, None)
        self.list.takeItem(self.list.row(item))

    def accept(self):
        # 表示順を保存 (並べ替え結果を反映)
        names_in_order = [self.list.item(i).text() for i in range(self.list.count())]
        reordered = {n: self._profiles[n] for n in names_in_order if n in self._profiles}
        save_profiles(reordered)
        super().accept()


# ---------------------------------------------------------------------------
# FTP接続ダイアログ（プロファイル保存・読み込み対応）
# ---------------------------------------------------------------------------

class FTPConnectDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("FTP接続")
        self.setMinimumWidth(380)
        self._profiles = load_profiles()

        layout = QVBoxLayout()
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        # --- プロファイル選択 ---
        profile_row = QHBoxLayout()
        profile_row.addWidget(QLabel("プロファイル:"))
        self.profile_combo = QComboBox()
        self.profile_combo.setMinimumWidth(160)
        self.profile_combo.addItem("-- 新規 --")
        for name in self._profiles:
            self.profile_combo.addItem(name)
        profile_row.addWidget(self.profile_combo, 1)
        self.save_btn = QPushButton("保存")
        self.manage_btn = QPushButton("管理")
        self.manage_btn.setToolTip("プロファイルの並べ替え / 名前変更 / 削除")
        profile_row.addWidget(self.save_btn)
        profile_row.addWidget(self.manage_btn)
        layout.addLayout(profile_row)

        layout.addSpacing(6)

        # --- 接続情報フォーム ---
        g = QGridLayout()
        g.addWidget(QLabel("ホスト:"), 0, 0)
        self.host = QLineEdit()
        self.host.setPlaceholderText("ftp.example.com")
        g.addWidget(self.host, 0, 1)

        g.addWidget(QLabel("ポート:"), 1, 0)
        self.port = QLineEdit("21")
        g.addWidget(self.port, 1, 1)

        g.addWidget(QLabel("ユーザー名:"), 2, 0)
        self.user = QLineEdit("anonymous")
        g.addWidget(self.user, 2, 1)

        g.addWidget(QLabel("パスワード:"), 3, 0)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        g.addWidget(self.password, 3, 1)
        layout.addLayout(g)

        layout.addSpacing(6)

        # --- 接続・キャンセル ---
        btns = QHBoxLayout()
        ok = QPushButton("接続")
        # 主アクション → 緑で強調 (LogViewer のサーバー接続ボタンと統一)
        ok.setStyleSheet(
            "QPushButton{background:#3a6e3a;color:#e0f0e0;border:1px solid #4a8e4a;"
            "font-weight:600;padding:3px 14px;border-radius:2px;}"
            "QPushButton:hover{background:#4a8e4a;border:1px solid #5aa05a;}"
        )
        ok.setDefault(True)
        cancel = QPushButton("キャンセル")
        btns.addWidget(ok)
        btns.addWidget(cancel)
        layout.addLayout(btns)
        self.setLayout(layout)

        # シグナル
        self.profile_combo.currentIndexChanged.connect(self._on_profile_selected)
        self.save_btn.clicked.connect(self._save_profile)
        self.manage_btn.clicked.connect(self._manage_profiles)
        ok.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)

    def _manage_profiles(self):
        """管理ダイアログを開き、結果 (並べ替え/改名/削除) をコンボに反映。"""
        dlg = FTPProfileManagerDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            # 最新のプロファイルを読み直してコンボを再構築
            self._profiles = load_profiles()
            cur = self.profile_combo.currentText()
            self.profile_combo.blockSignals(True)
            self.profile_combo.clear()
            self.profile_combo.addItem("-- 新規 --")
            for n in self._profiles:
                self.profile_combo.addItem(n)
            # 元の選択を維持 (消えていたら新規)
            idx = self.profile_combo.findText(cur)
            self.profile_combo.setCurrentIndex(idx if idx >= 0 else 0)
            self.profile_combo.blockSignals(False)

    # --- プロファイル操作 ---

    def _on_profile_selected(self, idx):
        if idx == 0:
            return
        name = self.profile_combo.currentText()
        p = self._profiles.get(name, {})
        self.host.setText(p.get('host', ''))
        self.port.setText(str(p.get('port', 21)))
        self.user.setText(p.get('user', 'anonymous'))
        self.password.setText(p.get('password', ''))

    def _save_profile(self):
        current = self.profile_combo.currentText()
        default_name = '' if current == '-- 新規 --' else current
        name, ok = QInputDialog.getText(
            self, "プロファイルを保存", "プロファイル名:", text=default_name
        )
        if not ok or not name.strip():
            return
        name = name.strip()
        self._profiles[name] = {
            'host': self.host.text(),
            'port': int(self.port.text() or 21),
            'user': self.user.text(),
            'password': self.password.text(),
        }
        save_profiles(self._profiles)

        # コンボボックスを更新
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        self.profile_combo.addItem("-- 新規 --")
        for n in self._profiles:
            self.profile_combo.addItem(n)
        idx = self.profile_combo.findText(name)
        self.profile_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.profile_combo.blockSignals(False)

    def info(self):
        # 「-- 新規 --」を選んでいなければ、選択中のプロファイル名も返す
        name = self.profile_combo.currentText()
        profile_name = '' if name == '-- 新規 --' else name
        return {
            'host': self.host.text(),
            'port': int(self.port.text() or 21),
            'user': self.user.text(),
            'password': self.password.text(),
            'profile_name': profile_name,
        }


# ---------------------------------------------------------------------------
# FTPパネル
# ---------------------------------------------------------------------------

class _FtpDownloadWorker(QThread):
    """ftplib.retrbinary を別スレッドで実行し、進捗を通知するワーカー。
    UI 側は QProgressDialog で進捗 / 速度 / キャンセルを扱う。
    """
    progress     = pyqtSignal(int)   # 累計取得バイト数
    finished_ok  = pyqtSignal(str)   # 完了時: ローカルパス
    finished_err = pyqtSignal(str)   # エラー時: 例外メッセージ

    def __init__(self, ftp, remote_name: str, local_path: str, parent=None):
        super().__init__(parent)
        self._ftp = ftp
        self._remote_name = remote_name
        self._local_path = local_path
        self._cancelled = False
        self._downloaded = 0

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            with open(self._local_path, 'wb') as f:
                def _on_chunk(chunk: bytes):
                    if self._cancelled:
                        # retrbinary のコールバック内で例外を投げると中断できる
                        raise RuntimeError("CANCELLED_BY_USER")
                    f.write(chunk)
                    self._downloaded += len(chunk)
                    self.progress.emit(self._downloaded)
                self._ftp.retrbinary(f'RETR {self._remote_name}', _on_chunk)
            self.finished_ok.emit(self._local_path)
        except RuntimeError as e:
            if 'CANCELLED_BY_USER' in str(e):
                # 中途半端な一時ファイルは削除
                try: os.remove(self._local_path)
                except Exception: pass
                self.finished_err.emit("ユーザーがキャンセルしました")
            else:
                self.finished_err.emit(str(e))
        except Exception as e:
            try: os.remove(self._local_path)
            except Exception: pass
            self.finished_err.emit(str(e))


_FTP_MONTH_MAP = {
    'Jan': 1, 'Feb': 2, 'Mar': 3, 'Apr': 4, 'May': 5, 'Jun': 6,
    'Jul': 7, 'Aug': 8, 'Sep': 9, 'Oct': 10, 'Nov': 11, 'Dec': 12,
}


def _ftp_list_date_to_iso(date_parts, convert_to_local: bool = False) -> str:
    """ftp LIST 出力の月日時刻 3 要素 (例: ['May','22','16:51'] や
    ['May','22','2025']) を 'YYYY/MM/DD HH:MM' に変換する。
    LIST には秒が含まれないので秒は表示しない。
    convert_to_local=True なら、 LIST 値を UTC とみなして OS のローカル TZ に
    変換する (大半の Unix FTP は LIST を UTC で返す)。
    形式が解析できない場合は元の連結文字列を返す。"""
    if len(date_parts) < 3:
        return ' '.join(date_parts)
    mon_str, day_str, time_or_year = date_parts[0], date_parts[1], date_parts[2]
    month = _FTP_MONTH_MAP.get(mon_str)
    if month is None:
        return ' '.join(date_parts)
    try:
        day = int(day_str)
    except ValueError:
        return ' '.join(date_parts)
    import datetime as _dt
    import calendar as _cal
    import time as _time
    now = _dt.datetime.now()
    if ':' in time_or_year:
        # 時刻形式 → 年は省略されているので推測 (= 現在 / 1年前)
        # ls の慣習: 過去 6 か月以内なら現在年、それ以上なら前年
        try:
            hh_str, mm_str = time_or_year.split(':')
            hh, mm = int(hh_str), int(mm_str)
        except ValueError:
            return ' '.join(date_parts)
        year = now.year
        try:
            candidate = _dt.datetime(year, month, day, hh, mm)
            # 現在より未来になった (= 来年扱い) なら 1 年戻す
            if candidate > now + _dt.timedelta(days=1):
                year -= 1
        except ValueError:
            pass
        if convert_to_local:
            try:
                naive_utc = _dt.datetime(year, month, day, hh, mm)
                utc_seconds = _cal.timegm(naive_utc.timetuple())
                local = _time.localtime(utc_seconds)
                return _time.strftime('%Y/%m/%d %H:%M', local)
            except Exception:
                pass
        return f"{year:04d}/{month:02d}/{day:02d} {hh:02d}:{mm:02d}"
    else:
        # 年指定形式 (時刻不明)。 時刻が無いので TZ 変換は意味がない。
        try:
            year = int(time_or_year)
        except ValueError:
            return ' '.join(date_parts)
        return f"{year:04d}/{month:02d}/{day:02d} 00:00"


def _ftp_mlsd_modify_to_local(modify: str, convert_to_local: bool = True) -> str:
    """MLSD の modify (RFC 3659: 'YYYYMMDDHHMMSS[.fff]' UTC) を
    'YYYY/MM/DD HH:MM' にフォーマット。 convert_to_local=True なら
    UTC とみなして OS のローカル TZ に変換、 False なら数値部だけを
    そのまま整形 (= サーバー値生表示)。 パース失敗時は元文字列を返す。
    PyInstaller 等で `datetime.astimezone()` がローカル TZ を引けない
    (UTC のままになる) ケースがあるため、 calendar.timegm + time.localtime
    で OS のローカル TZ を経由して変換する。"""
    if not modify:
        return ''
    import calendar as _cal
    import datetime as _dt
    import time as _time
    try:
        dt_utc_naive = _dt.datetime.strptime(modify[:14], '%Y%m%d%H%M%S')
        if convert_to_local:
            utc_seconds = _cal.timegm(dt_utc_naive.timetuple())
            local_struct = _time.localtime(utc_seconds)
            return _time.strftime('%Y/%m/%d %H:%M', local_struct)
        return dt_utc_naive.strftime('%Y/%m/%d %H:%M')
    except Exception:
        return modify


def _fmt_bytes(n: int) -> str:
    """バイト数を人間に読みやすい単位 (B/KB/MB/GB) で整形する。"""
    if n < 1024:
        return f"{n} B"
    for unit in ('KB', 'MB', 'GB'):
        n /= 1024
        if n < 1024:
            return f"{n:.1f} {unit}"
    return f"{n:.1f} TB"


class _FTPSizeDelegate(QStyledItemDelegate):
    """FTPファイル一覧用デリゲート (2行表示)。
    1行目に名前 (幅が足りなければ … で省略)、2行目にサイズ・日時を淡色小フォントで表示する。
    メタ情報文字列 (例 "1.2 MB · May 22 16:51") は UserRole+1 に格納されている前提。
    メタが無い項目 (フォルダ / 親フォルダ) は従来通り1行で縦中央に名前のみ描画する。
    """
    _META_ROLE = Qt.ItemDataRole.UserRole + 1

    def _small_font(self, base: QFont) -> QFont:
        f = QFont(base)
        f.setPointSizeF(max(base.pointSizeF() - 1.5, 6.0))
        return f

    def sizeHint(self, option, index):
        base = super().sizeHint(option, index)
        if not index.data(self._META_ROLE):
            return base
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        nfm = QFontMetrics(opt.font)
        sfm = QFontMetrics(self._small_font(opt.font))
        h = nfm.height() + sfm.height() + 6   # 上下 padding
        return QSize(base.width(), max(base.height(), h))

    def paint(self, painter, option, index):
        meta = index.data(self._META_ROLE) or ''

        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        name = opt.text
        opt.text = ''   # テキストは自前で描くので標準描画から外す (背景/選択のみ描かせる)
        widget = opt.widget
        style = widget.style() if widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, widget)

        text_rect = style.subElementRect(
            QStyle.SubElement.SE_ItemViewItemText, opt, widget
        )
        painter.save()
        selected = bool(opt.state & QStyle.StateFlag.State_Selected)

        # 名前色: 選択中もテーマの text 色を使う (HighlightedText = 白だと
        # Light テーマの淡水色 selection 背景で文字が見えなくなるため)。
        # Dark テーマでも text = 明色 / selection = 濃青 で読みやすい。
        fg = index.data(Qt.ItemDataRole.ForegroundRole)
        if fg is not None and hasattr(fg, 'color'):
            name_color = fg.color()           # ディレクトリ等の指定色を尊重
        elif fg is not None:
            name_color = QColor(fg)
        else:
            name_color = QColor(_theme()['text'])

        left = text_rect.left() + 2
        right_pad = 6
        avail_w = max(text_rect.width() - 2 - right_pad, 0)

        name_font = opt.font
        nfm = QFontMetrics(name_font)

        if not meta:
            # 1行: 縦中央に名前のみ (フォルダ / 親フォルダ)
            painter.setFont(name_font)
            painter.setPen(name_color)
            elided = nfm.elidedText(name, Qt.TextElideMode.ElideRight, avail_w)
            painter.drawText(
                text_rect.adjusted(2, 0, -right_pad, 0),
                int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                elided,
            )
            painter.restore()
            return

        # 2行: 名前 (上) + サイズ・日時 (下 / 淡色小フォント)
        small_font = self._small_font(name_font)
        sfm = QFontMetrics(small_font)
        total_h = nfm.height() + sfm.height()
        top = text_rect.top() + max((text_rect.height() - total_h) // 2, 0)

        # 1行目: 名前
        painter.setFont(name_font)
        painter.setPen(name_color)
        name_elided = nfm.elidedText(name, Qt.TextElideMode.ElideRight, avail_w)
        painter.drawText(left, top + nfm.ascent(), name_elided)

        # 2行目: メタ (アイコン分インデントして名前の直下に揃える)
        indent = nfm.horizontalAdvance("📄 ")
        painter.setFont(small_font)
        meta_color = (name_color if selected else QColor("#7a8290"))
        painter.setPen(meta_color)
        meta_elided = sfm.elidedText(meta, Qt.TextElideMode.ElideRight,
                                     max(avail_w - indent, 0))
        painter.drawText(left + indent, top + nfm.height() + sfm.ascent(), meta_elided)
        painter.restore()


class FTPPanel(QWidget):
    file_downloaded      = pyqtSignal(str, str)  # content, filename (互換用)
    file_downloaded_path = pyqtSignal(str, str)  # local_path, filename (新規)
    # DL 開始直前に local_path を通知 → MainWindow が _self_write_paths に登録
    # することで、DL 中の chunk 書込みで発火する fileChanged を無視させる。
    # これが無いと:
    # - DL 中の partial 書込みで _on_external_change が走り、未編集タブを
    #   不完全な内容で auto-reload してしまう
    # - DL 完了後の _open_ftp_file で setModified が伝わる前に dialog が出る
    download_starting    = pyqtSignal(str)       # local_path

    def __init__(self, parent=None):
        super().__init__(parent)
        self.ftp = None
        self.current_path = '/'
        # 接続中の保存済みプロファイル名 (空文字 = 一時接続/--新規--)
        self._active_profile_name: str = ''
        # 再接続用に最後の接続情報を保持
        self._last_conn_info: dict = {}
        # ローカルパスを渡して「未保存編集あり」かを返すコールバック (MainWindow が注入)
        self._is_modified_cb = lambda _local_path: False

        # キープアライブタイマー: 60秒毎に NOOP を送ってアイドルタイムアウトを防ぐ
        self._keepalive_timer = QTimer(self)
        self._keepalive_timer.setInterval(60_000)
        self._keepalive_timer.timeout.connect(self._send_keepalive)

    def set_modification_checker(self, fn):
        """MainWindow から呼ぶ: 引数local_path → bool (未保存編集あり) を返す関数 + UI を構築"""
        self._is_modified_cb = fn

        layout = QVBoxLayout()
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)

        self.status_label = QLabel("未接続")
        layout.addWidget(self.status_label)

        btns = QHBoxLayout()
        self.connect_btn = QPushButton("接続")
        self.disconnect_btn = QPushButton("切断")
        self.disconnect_btn.setEnabled(False)
        btns.addWidget(self.connect_btn)
        btns.addWidget(self.disconnect_btn)
        layout.addLayout(btns)

        self.path_label = QLabel("/")
        layout.addWidget(self.path_label)
        self.apply_theme()

        self.file_list = QListWidget()
        # 複数選択を有効化 (Ctrl/Shift クリックで複数選択 → 一括ダウンロード可)
        self.file_list.setSelectionMode(
            QListWidget.SelectionMode.ExtendedSelection
        )
        self.file_list.setToolTip(
            "Ctrl+クリック または Shift+クリック で複数選択可能\n"
            "複数選択時は「開く / ダウンロード」ボタンでまとめて取得"
        )
        # 名前=左寄せ(省略可)/ サイズ=右端淡色 で描画するデリゲート
        self.file_list.setItemDelegate(_FTPSizeDelegate(self.file_list))
        layout.addWidget(self.file_list)

        self.open_btn = QPushButton("開く / ダウンロード")
        self.open_btn.setEnabled(False)
        layout.addWidget(self.open_btn)

        self.setLayout(layout)

        self.connect_btn.clicked.connect(self._connect)
        self.disconnect_btn.clicked.connect(self._disconnect)
        self.file_list.itemDoubleClicked.connect(self._on_double_click)
        self.file_list.itemSelectionChanged.connect(self._on_selection)
        self.open_btn.clicked.connect(self._open_selected)

    def apply_theme(self):
        """パス欄・状態ラベルをテーマ連動で再スタイル。"""
        t = _theme()
        if hasattr(self, 'path_label'):
            self.path_label.setStyleSheet(
                f"padding:3px; background:{t['control_bg']}; color:{t['text']};"
            )
        # 未接続時のみ状態ラベルを既定色に (接続中は接続処理側で色を上書き)
        if hasattr(self, 'status_label') and self.ftp is None:
            self.status_label.setStyleSheet(f"color:{t['text_dim']}; padding:2px;")

    # --- FTP operations ---

    def _connect(self):
        dlg = FTPConnectDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        info = dlg.info()
        try:
            self.ftp = ftplib.FTP()
            self.ftp.connect(info['host'], info['port'], timeout=10)
            self.ftp.login(info['user'], info['password'])
            # 接続表示: 保存済みプロファイル名があればそれを優先、無ければホスト
            display_name = info.get('profile_name') or info['host']
            self.status_label.setText(f"接続中: {display_name}")
            # 明るい緑にして視認性アップ (旧 #6A8759 は暗くて読みにくいため)
            self.status_label.setStyleSheet(
                "background: #A5D6A7; color: #000000; padding: 2px;"
            )
            self.status_label.setToolTip(f"ホスト: {info['host']}  ユーザー: {info['user']}")
            self.connect_btn.setEnabled(False)
            self.disconnect_btn.setEnabled(True)

            # 接続中プロファイル名 + 再接続用に接続情報を保持
            self._active_profile_name = info.get('profile_name', '')
            self._last_conn_info = dict(info)

            # キープアライブ開始 (アイドルタイムアウト切断防止)
            self._keepalive_timer.start()

            # プロファイルに last_dir があれば自動 cd を試みる
            initial_dir = '/'
            if self._active_profile_name:
                profs = load_profiles()
                saved_dir = (profs.get(self._active_profile_name, {}) or {}).get('last_dir')
                if saved_dir:
                    try:
                        # cwd できるかテスト (失敗してもエラーにせず / にフォールバック)
                        self.ftp.cwd(saved_dir)
                        initial_dir = saved_dir
                    except Exception:
                        initial_dir = '/'
            self._list(initial_dir)
        except Exception as e:
            QMessageBox.critical(self, "接続エラー", str(e))

    def _disconnect(self):
        # 切断前に最新ディレクトリを永続化しておく
        self._persist_last_dir()
        self._keepalive_timer.stop()
        if self.ftp:
            try:
                self.ftp.quit()
            except Exception:
                pass
            self.ftp = None
        self._active_profile_name = ''
        self._last_conn_info = {}
        self.status_label.setText("未接続")
        self.status_label.setStyleSheet("color: #808080; padding: 2px;")
        self.connect_btn.setEnabled(True)
        self.disconnect_btn.setEnabled(False)
        self.file_list.clear()
        self.open_btn.setEnabled(False)

    def _send_keepalive(self):
        """定期的に NOOP を送ってアイドル切断を防ぐ。失敗時は自動再接続を試みる。"""
        if self.ftp is None:
            return
        try:
            # NOOP は何もしないコマンド (タイマーをリセットする副作用のみ)
            self.ftp.voidcmd('NOOP')
        except Exception:
            # 接続が死んでいた → 自動再接続を試みる
            self._reconnect_silent()

    def _reconnect_silent(self) -> bool:
        """保存済み接続情報で静かに再接続。成功 = True / 失敗 = False。"""
        info = dict(self._last_conn_info or {})
        if not info:
            return False
        try:
            try:
                if self.ftp:
                    self.ftp.close()
            except Exception:
                pass
            self.ftp = ftplib.FTP()
            self.ftp.connect(info['host'], info['port'], timeout=10)
            self.ftp.login(info['user'], info['password'])
            # 接続前にいた DIR を復元
            if self.current_path and self.current_path != '/':
                try:
                    self.ftp.cwd(self.current_path)
                except Exception:
                    pass
            return True
        except Exception:
            # 再接続失敗 → タイマー停止して切断状態に
            self._keepalive_timer.stop()
            self.ftp = None
            self.status_label.setText("接続が切れました (再接続失敗)")
            self.status_label.setStyleSheet("color: #FF8080; padding: 2px;")
            self.connect_btn.setEnabled(True)
            self.disconnect_btn.setEnabled(False)
            return False

    def _ensure_alive(self) -> bool:
        """通信前に接続の生存確認。死んでいたら自動再接続。"""
        if self.ftp is None:
            return False
        try:
            self.ftp.voidcmd('NOOP')
            return True
        except Exception:
            return self._reconnect_silent()

    def _persist_last_dir(self):
        """現在のディレクトリを接続中プロファイルに保存 (次回接続時の初期DIRに使う)。"""
        name = self._active_profile_name
        if not name:
            return  # 一時接続は記憶しない
        try:
            profs = load_profiles()
            if name not in profs:
                return
            # 同じ値なら書き込みスキップ (無駄な disk write を減らす)
            if profs[name].get('last_dir') == self.current_path:
                return
            profs[name]['last_dir'] = self.current_path
            save_profiles(profs)
        except Exception:
            pass

    def _list(self, path):
        if not self.ftp:
            return
        # 通信前に接続生存を確認、死んでいたら自動再接続
        if not self._ensure_alive():
            QMessageBox.warning(self, "接続切断",
                "FTP 接続が切れました。再接続に失敗したので再度接続してください。")
            return
        try:
            self.ftp.cwd(path)
            self.current_path = self.ftp.pwd()
            self.path_label.setText(self.current_path)
            self.file_list.clear()
            # 接続プロファイルが特定済みなら最新ディレクトリを永続化
            self._persist_last_dir()

            if self.current_path != '/':
                item = QListWidgetItem("[..] 親フォルダへ")
                item.setData(Qt.ItemDataRole.UserRole, ('dir', '..'))
                item.setForeground(QColor("#6897BB"))
                self.file_list.addItem(item)

            # 時刻表示モード:
            #  - 'local' (デフォルト): サーバー値 (LIST/MLSD) を UTC とみなして
            #             OS のローカル TZ に変換。 FFFTP の TZ=GMT 設定と同じ。
            #  - 'raw'   : サーバー値をそのまま表示 (既にローカル TZ で報告する
            #             サーバー向け)
            time_mode = SETTINGS.get('ftp_time_mode', 'local')
            convert_to_local = (time_mode == 'local')
            # MLSD は raw でも local でも試す価値あり (取れたら時刻精度が秒単位)。
            try:
                mlsd_entries = list(self.ftp.mlsd())
            except Exception:
                mlsd_entries = None

            if mlsd_entries is not None:
                for name, facts in mlsd_entries:
                    if name in ('.', '..'):
                        continue
                    typ = facts.get('type', '')
                    is_dir = typ in ('dir', 'cdir', 'pdir')
                    if is_dir:
                        item = QListWidgetItem(f"📁 {name}")
                        item.setData(Qt.ItemDataRole.UserRole, ('dir', name))
                        item.setForeground(QColor("#6897BB"))
                        item.setToolTip(name)
                    else:
                        item = QListWidgetItem(f"📄 {name}")
                        item.setData(Qt.ItemDataRole.UserRole, ('file', name))
                        size_str = ''
                        try:
                            size_str = _fmt_bytes(int(facts.get('size', '0')))
                        except (ValueError, TypeError):
                            size_str = ''
                        date_str = _ftp_mlsd_modify_to_local(
                            facts.get('modify', ''),
                            convert_to_local=convert_to_local,
                        )
                        meta = ' · '.join(s for s in (size_str, date_str) if s)
                        if meta:
                            item.setData(Qt.ItemDataRole.UserRole + 1, meta)
                            item.setToolTip(f"{name}\n{meta}")
                        else:
                            item.setToolTip(name)
                    self.file_list.addItem(item)
            else:
                lines = []
                self.ftp.retrlines('LIST', lines.append)
                for line in lines:
                    parts = line.split()
                    if len(parts) < 9:
                        continue
                    is_dir = parts[0].startswith('d')
                    name = ' '.join(parts[8:])
                    if is_dir:
                        item = QListWidgetItem(f"📁 {name}")
                        item.setData(Qt.ItemDataRole.UserRole, ('dir', name))
                        item.setForeground(QColor("#6897BB"))
                        item.setToolTip(name)
                    else:
                        item = QListWidgetItem(f"📄 {name}")
                        item.setData(Qt.ItemDataRole.UserRole, ('file', name))
                        # LIST (ls -l 形式): 5列目=バイト数, 6-8列目=月 日 時刻/年
                        size_str = ''
                        try:
                            size_str = _fmt_bytes(int(parts[4]))
                        except (ValueError, IndexError):
                            size_str = ''
                        # LIST の "May 22 16:51" / "May 22 2025" を
                        # "YYYY/MM/DD HH:MM" 形式に変換 (秒は LIST に無い)。
                        # 'local' モードなら LIST 値を UTC とみなして変換
                        date_str = _ftp_list_date_to_iso(
                            parts[5:8], convert_to_local=convert_to_local)
                        meta = ' · '.join(s for s in (size_str, date_str) if s)
                        if meta:
                            item.setData(Qt.ItemDataRole.UserRole + 1, meta)
                            item.setToolTip(f"{name}\n{meta}")
                        else:
                            item.setToolTip(name)
                    self.file_list.addItem(item)
        except Exception as e:
            QMessageBox.warning(self, "エラー", str(e))

    def _on_double_click(self, item):
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data:
            return
        kind, name = data
        if kind == 'dir':
            if name == '..':
                parent = '/'.join(self.current_path.rstrip('/').split('/')[:-1]) or '/'
                self._list(parent)
            else:
                self._list(self.current_path.rstrip('/') + '/' + name)
        else:
            self._download(name)

    def _on_selection(self):
        """選択中にファイルが1つでも含まれていれば「開く/ダウンロード」を有効化。
        フォルダ単独選択や未選択時は無効。複数件選択時はボタン名を切替。"""
        items = self.file_list.selectedItems()
        file_count = 0
        for it in items:
            d = it.data(Qt.ItemDataRole.UserRole)
            if d and d[0] == 'file':
                file_count += 1
        self.open_btn.setEnabled(file_count > 0)
        if file_count > 1:
            self.open_btn.setText(f"開く / ダウンロード ({file_count} 件)")
        else:
            self.open_btn.setText("開く / ダウンロード")

    def _open_selected(self):
        items = self.file_list.selectedItems()
        files = [it.data(Qt.ItemDataRole.UserRole)[1]
                 for it in items
                 if it.data(Qt.ItemDataRole.UserRole)
                 and it.data(Qt.ItemDataRole.UserRole)[0] == 'file']
        if not files:
            return
        if len(files) == 1:
            self._download(files[0])
        else:
            self._download_many(files)

    def _download_many(self, names):
        """複数ファイルを順次ダウンロード (各ファイルにつき進捗ダイアログを表示)。
        途中でキャンセルされたら以降の処理も中止。"""
        total_n = len(names)
        completed = []
        for i, name in enumerate(names, 1):
            # 状態ラベルに「i/N」を表示
            self.status_label.setText(f"複数DL: {i}/{total_n} {name} を取得中...")
            QApplication.processEvents()
            # _download は内部で進捗ダイアログを出すので、ここでは1件ずつ呼ぶだけ
            # 各 _download の最後で file_downloaded_path シグナルが発火 → タブで開く
            try:
                self._download(name)
                completed.append(name)
            except Exception as e:
                QMessageBox.warning(self, "ダウンロードエラー", f"{name}: {e}")
                # 続行確認
                ans = QMessageBox.question(
                    self, "続行確認",
                    f"{name} のダウンロードに失敗しました。\n残り {total_n - i} 件のダウンロードを続けますか?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if ans != QMessageBox.StandardButton.Yes:
                    break
        # 完了表示 (ステータス) — 接続中に戻す
        display_name = self._active_profile_name or getattr(self.ftp, 'host', 'ftp')
        self.status_label.setText(
            f"接続中: {display_name}  (完了: {len(completed)}/{total_n} 件)"
        )

    # サイズ閾値
    _SIZE_WARN = 5 * 1024 * 1024       # 5 MB
    _SIZE_HARD = 100 * 1024 * 1024     # 100 MB

    def _download(self, name):
        if not self.ftp:
            return
        # 通信前に接続生存を確認、死んでいたら自動再接続
        if not self._ensure_alive():
            QMessageBox.warning(self, "接続切断",
                "FTP 接続が切れました。再接続に失敗したので再度接続してください。")
            return

        # 1. サイズ事前取得 (SIZE コマンド非対応サーバーは 0 扱い)
        size = 0
        try:
            size = self.ftp.size(name) or 0
        except Exception:
            size = 0

        # 2. 警告 / 確認
        if size >= self._SIZE_HARD:
            mb = size // 1024 // 1024
            ans = QMessageBox.warning(
                self, "ファイルが非常に大きい",
                f"{name} は {mb} MB あります。\n"
                "メモリ不足やUIフリーズの可能性があります。\n"
                "それでもダウンロードしますか？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if ans != QMessageBox.StandardButton.Yes:
                return
        elif size >= self._SIZE_WARN:
            mb = size / 1024 / 1024
            ans = QMessageBox.question(
                self, "サイズ確認",
                f"{name} は約 {mb:.1f} MB あります。\nダウンロードを続けますか？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if ans != QMessageBox.StandardButton.Yes:
                return

        # 3. 一時ファイルへストリーム保存 (メモリ消費を抑える)
        import tempfile
        host = getattr(self.ftp, 'host', 'ftp')
        host_tag = re.sub(r'[^\w.-]', '_', host or 'ftp')
        tmp_dir = os.path.join(tempfile.gettempdir(), 'text_editor_ftp', host_tag)
        os.makedirs(tmp_dir, exist_ok=True)
        local_path = os.path.join(tmp_dir, os.path.basename(name))

        # 3a. ローカルで編集中なら上書き確認
        if os.path.exists(local_path) and self._is_modified_cb(local_path):
            ans = QMessageBox.warning(
                self, "ローカルで編集中",
                f"{name} はタブで未保存の変更があります。\n"
                "FTP から再取得すると編集内容が失われます。\n"
                "上書きしますか？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if ans != QMessageBox.StandardButton.Yes:
                return

        # 4. プログレスダイアログ + 別スレッドでダウンロード
        # (大きいファイルでも UI が固まらないように)
        # サイズ不明 (size=0) の時は最大値 0 でビジー表示
        progress = QProgressDialog(
            f"ダウンロード中: {name}",
            "キャンセル",
            0,
            max(size, 0),
            self,
        )
        progress.setWindowTitle("FTP ダウンロード")
        progress.setMinimumDuration(0)
        progress.setMinimumWidth(420)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        t = _theme()
        progress.setStyleSheet(
            f"QProgressDialog {{ background:{t['bg']}; }}"
            f"QLabel {{ color:{t['text']}; }}"
            f"QPushButton {{ background:{t['control_bg']}; color:{t['text']}; border:none;"
            f"              padding:4px 12px; border-radius:2px; }}"
            f"QPushButton:hover {{ background:{t['control_hover']}; }}"
            f"QProgressBar {{ background:{t['editor_bg']}; color:{t['text']};"
            f"               border:1px solid {t['border']}; border-radius:2px;"
            f"               text-align:center; }}"
            "QProgressBar::chunk { background:#4a8e4a; }"
        )

        worker = _FtpDownloadWorker(self.ftp, name, local_path, self)
        # 経過時間 / 速度算出用
        import time as _time
        t_start = _time.monotonic()

        def _on_progress(done: int):
            elapsed = _time.monotonic() - t_start
            speed_str = ""
            eta_str = ""
            if elapsed > 0.2:
                speed = done / elapsed   # bytes/sec
                speed_str = f"  ({_fmt_bytes(int(speed))}/s)"
                if size > 0 and speed > 0:
                    remaining = max(0, size - done)
                    eta = remaining / speed
                    eta_str = f"  残り {eta:.0f} 秒"
            if size > 0:
                pct = int(done * 100 / size) if size else 0
                progress.setValue(done)
                progress.setLabelText(
                    f"ダウンロード中: {name}\n"
                    f"{_fmt_bytes(done)} / {_fmt_bytes(size)}  ({pct}%){speed_str}{eta_str}"
                )
            else:
                progress.setLabelText(
                    f"ダウンロード中: {name}\n"
                    f"{_fmt_bytes(done)}{speed_str}  (合計サイズ不明)"
                )

        worker.progress.connect(_on_progress)

        # 完了/エラー処理 — Qt の queued signal はワーカースレッドから main
        # スレッドにディスパッチされる。worker.isRunning() で待つだけだと
        # スレッド終了直後にシグナル到達前のタイミングで抜けてしまうため、
        # 「シグナルが届くまで」を完了条件にする (done フラグ方式)。
        result = {'ok': False, 'err': '', 'path': '', 'done': False}

        def _on_ok(path: str):
            result['ok'] = True
            result['path'] = path
            result['done'] = True
            progress.setValue(max(size, 1))
            progress.close()

        def _on_err(err: str):
            result['err'] = err
            result['done'] = True
            progress.close()

        worker.finished_ok.connect(_on_ok)
        worker.finished_err.connect(_on_err)
        progress.canceled.connect(worker.cancel)

        # DL 中の fileChanged を抑止するため MainWindow に local_path を通達
        self.download_starting.emit(local_path)
        worker.start()
        # done フラグが立つまで Qt イベントループを回す
        # (進捗ダイアログはモーダルなのでユーザーは他の FTP 操作を打てない)
        while not result['done']:
            QApplication.processEvents()
            # CPU 100%を避けるため、進行中は短時間待機
            if worker.isRunning():
                worker.wait(30)
            else:
                # スレッドは終わってるが queued signal がまだ届いていない
                # 数回 processEvents() を回せば届く
                worker.wait(5)
        # 最後にスレッドが完全に終了するのを待つ (リソースリーク防止)
        worker.wait()

        if result['ok']:
            self.file_downloaded_path.emit(local_path, name)
        else:
            if result['err'] and 'キャンセル' not in result['err']:
                QMessageBox.warning(self, "ダウンロードエラー", result['err'])


# ---------------------------------------------------------------------------
# ブックマークパネル
# ---------------------------------------------------------------------------

class BookmarkPanel(QWidget):
    jump_requested = pyqtSignal(object, int)  # EditorTab, lineno
    close_requested = pyqtSignal()
    bookmarks_cleared = pyqtSignal()          # 全削除後に発火 (永続化更新用)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tab_refs: list[tuple[str, object]] = []  # (label, EditorTab)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)

        header = QHBoxLayout()
        header.addWidget(QLabel("🔖 ブックマーク一覧"))
        refresh_btn = QPushButton("更新")
        refresh_btn.setMaximumWidth(50)
        refresh_btn.clicked.connect(self._refresh)
        clear_btn = QPushButton("全削除")
        clear_btn.setMaximumWidth(60)
        clear_btn.clicked.connect(self._clear_all)
        # 閉じるボタン (テーマ連動)
        self.close_btn = QPushButton("✕")
        self.close_btn.setFixedWidth(28)
        self.close_btn.setToolTip("ブックマーク一覧を閉じる (Esc)")
        self.close_btn.clicked.connect(self.close_requested.emit)
        header.addStretch()
        header.addWidget(refresh_btn)
        header.addWidget(clear_btn)
        header.addWidget(self.close_btn)
        layout.addLayout(header)
        self.apply_theme()

        self.list_widget = QListWidget()
        self.list_widget.itemDoubleClicked.connect(self._on_double_click)
        layout.addWidget(self.list_widget)

        self._hint_label = QLabel(
            "ダブルクリックでジャンプ  /  F2：登録/解除  /  F3：次へ  /  Shift+F3：前へ"
        )
        self._hint_label.setWordWrap(True)   # 右サイドバーは幅が狭いので折り返す
        layout.addWidget(self._hint_label)
        self.setLayout(layout)
        # ヒント色をテーマに合わせる (Light テーマで薄い灰色だと読めないため)
        self._apply_hint_color()

    def apply_theme(self):
        """閉じる(×)ボタンをテーマ連動で再スタイル (ホバーは赤=閉じる/削除色)。"""
        if not hasattr(self, 'close_btn'):
            return
        t = _theme()
        self.close_btn.setStyleSheet(
            f"QPushButton {{ background:{t['control_bg']}; color:{t['text']};"
            f"              border:1px solid {t['border']};"
            f"              padding:2px 4px; border-radius:3px; font-weight:600; }}"
            f"QPushButton:hover {{ background:#c0392b; color:#fff; border:1px solid #e05545; }}"
        )
        # ヒント文字色もテーマ連動で更新 (Light モードで読みにくいため)
        self._apply_hint_color()
        # 既存のアイテム色も塗り直す
        if hasattr(self, 'list_widget'):
            self._refresh()

    def _apply_hint_color(self):
        if not hasattr(self, '_hint_label'):
            return
        is_light = SETTINGS.get('theme', 'Dark') in ('Light', 'Solarized Light')
        c = '#555555' if is_light else '#a0a6ad'
        self._hint_label.setStyleSheet(f"color: {c}; font-size: 11px;")

    @staticmethod
    def _bookmark_colors():
        """Light モードでは濃い色、それ以外は明るい色を返す。
        (header, normal, error, warn) のタプル。"""
        is_light = SETTINGS.get('theme', 'Dark') in ('Light', 'Solarized Light')
        if is_light:
            return ('#1565C0', '#0D47A1', '#B71C1C', '#E65100')  # 濃青 / 濃青 / 濃赤 / 濃橙
        return ('#6897BB', '#4A9EFF', '#FF7070', '#E8B26A')      # 明青 / 明青 / 明赤 / 明橙

    def keyPressEvent(self, event):
        # Esc キーで閉じる
        if event.key() == Qt.Key.Key_Escape:
            self.close_requested.emit()
            return
        super().keyPressEvent(event)

    def set_tabs(self, tab_refs: list[tuple[str, object]]):
        self._tab_refs = tab_refs
        self._refresh()

    def _refresh(self):
        self.list_widget.clear()
        header_c, normal_c, error_c, warn_c = self._bookmark_colors()
        for label, tab in self._tab_refs:
            editor = tab.editor
            linenos = sorted(editor._bookmarks)
            if not linenos:
                continue
            # このタブ (ファイル) のヘッダーを1回だけ挿入
            header_item = QListWidgetItem(f"📄 {label}")
            header_item.setFlags(Qt.ItemFlag.NoItemFlags)
            header_item.setForeground(QColor(header_c))
            self.list_widget.addItem(header_item)

            for lineno in linenos:
                block = editor.document().findBlockByNumber(lineno - 1)
                full_text = block.text().strip() if block.isValid() else ''
                # プレビューは長め (200文字) + 超過時は省略記号
                preview = full_text[:200]
                if len(full_text) > 200:
                    preview += ' …'
                item = QListWidgetItem(f"  行 {lineno:>5}   {preview}")
                item.setData(Qt.ItemDataRole.UserRole, (tab, lineno))
                # ホバーで全文を確認できるようツールチップに完全な行を入れる
                item.setToolTip(f"{label}  行 {lineno}\n{full_text}")
                # エラー行は赤、警告行は橙、その他は青 (テーマで濃淡切替)
                if re.search(r'\b(?:ERROR|CRITICAL|FATAL)\b', preview, re.IGNORECASE):
                    item.setForeground(QColor(error_c))
                elif re.search(r'\bWARN', preview, re.IGNORECASE):
                    item.setForeground(QColor(warn_c))
                else:
                    item.setForeground(QColor(normal_c))
                self.list_widget.addItem(item)

        # ブックマークが1つも無い場合は最小限の表示のみ (操作説明は下部の凡例にある)
        if self.list_widget.count() == 0:
            empty_item = QListWidgetItem("ブックマークはまだありません。")
            empty_item.setFlags(Qt.ItemFlag.NoItemFlags)
            empty_item.setForeground(QColor("#808080"))
            self.list_widget.addItem(empty_item)

    def _on_double_click(self, item):
        data = item.data(Qt.ItemDataRole.UserRole)
        if data:
            self.jump_requested.emit(data[0], data[1])

    def _clear_all(self):
        for _label, tab in self._tab_refs:
            tab.editor._bookmarks.clear()
            tab.editor.line_number_area.update()
        self._refresh()
        self.bookmarks_cleared.emit()


# ---------------------------------------------------------------------------
# Grep検索ワーカー（バックグラウンドスレッド）
# ---------------------------------------------------------------------------

class GrepWorker(QThread):
    result_found = pyqtSignal(str, int, str)  # filepath, lineno, line
    finished = pyqtSignal(int)                # total match count

    def __init__(self, directory, pattern, file_glob, case_sensitive, use_regex):
        super().__init__()
        self.directory = directory
        self.pattern = pattern
        self.file_glob = file_glob
        self.case_sensitive = case_sensitive
        self.use_regex = use_regex
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        globs = [g.strip() for g in self.file_glob.split(',') if g.strip()] or ['*']
        flags = 0 if self.case_sensitive else re.IGNORECASE
        try:
            pat = re.compile(self.pattern if self.use_regex else re.escape(self.pattern), flags)
        except re.error:
            self.finished.emit(0)
            return

        count = 0
        for root, dirs, files in os.walk(self.directory):
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            for fname in files:
                if self._stop:
                    break
                if not any(fnmatch.fnmatch(fname, g) for g in globs):
                    continue
                fpath = os.path.join(root, fname)
                # CP932/Shift_JIS なログ等にも対応するため、まずバイトで読み込み、
                # UTF-8 → CP932 → 最終 fallback の順で decode する。
                try:
                    with open(fpath, 'rb') as bf:
                        raw = bf.read()
                except Exception:
                    continue
                text = None
                for enc in ('utf-8-sig', 'utf-8', 'cp932', 'shift_jis', 'euc-jp'):
                    try:
                        text = raw.decode(enc)
                        break
                    except UnicodeDecodeError:
                        continue
                if text is None:
                    text = raw.decode('utf-8', errors='replace')
                try:
                    for lineno, line in enumerate(text.splitlines(), 1):
                        if pat.search(line):
                            self.result_found.emit(fpath, lineno, line.rstrip())
                            count += 1
                except Exception:
                    pass
            if self._stop:
                break
        self.finished.emit(count)


# ---------------------------------------------------------------------------
# Grepパネル（検索UI + 結果ツリー）
# ---------------------------------------------------------------------------

class _GrepMatchDelegate(QStyledItemDelegate):
    """Grep 結果のマッチ部分を黄色背景でハイライト描画するデリゲート。
    対象は QTreeWidget の column=1 (マッチ内容セル) のみ。
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self._pattern: str = ''
        self._case_sensitive: bool = False
        self._is_regex: bool = False
        self._compiled = None

    def set_pattern(self, pattern: str, case_sensitive: bool, is_regex: bool):
        self._pattern = pattern or ''
        self._case_sensitive = case_sensitive
        self._is_regex = is_regex
        # 正規表現はコンパイルしておく (描画ごとの再パースを避ける)
        self._compiled = None
        if pattern and is_regex:
            try:
                flags = 0 if case_sensitive else re.IGNORECASE
                self._compiled = re.compile(pattern, flags)
            except re.error:
                self._compiled = None

    def _find_matches(self, text: str) -> list[tuple[int, int]]:
        """マッチ位置の (start, end) リストを返す。"""
        if not text or not self._pattern:
            return []
        spans: list[tuple[int, int]] = []
        if self._is_regex:
            if self._compiled is None:
                return []
            for m in self._compiled.finditer(text):
                if m.start() != m.end():
                    spans.append((m.start(), m.end()))
        else:
            hay = text if self._case_sensitive else text.lower()
            ndl = self._pattern if self._case_sensitive else self._pattern.lower()
            n = len(ndl)
            if n == 0:
                return []
            i = 0
            while True:
                p = hay.find(ndl, i)
                if p < 0:
                    break
                spans.append((p, p + n))
                i = p + n
        return spans

    def paint(self, painter, option, index):
        # マッチ内容列以外は通常描画
        if index.column() != 1 or not self._pattern:
            super().paint(painter, option, index)
            return
        text = index.data(Qt.ItemDataRole.DisplayRole) or ''
        spans = self._find_matches(text)
        if not spans:
            super().paint(painter, option, index)
            return

        # 通常の背景・選択状態を先に描画
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        # テキスト部分は自前で描くので空に
        original_text = opt.text
        opt.text = ''
        widget = opt.widget
        style = widget.style() if widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, widget)

        # テキスト描画矩形を取得
        text_rect = style.subElementRect(
            QStyle.SubElement.SE_ItemViewItemText, opt, widget
        )
        painter.save()
        painter.setClipRect(text_rect)
        painter.setFont(opt.font)

        # 通常文字色 (選択中は強調色)
        fg = opt.palette.color(
            opt.palette.ColorGroup.Active,
            opt.palette.ColorRole.HighlightedText if (opt.state & QStyle.StateFlag.State_Selected)
            else opt.palette.ColorRole.Text
        )
        hl_bg = QColor("#FFEB3B")   # マッチ背景: 鮮やかな黄色
        hl_fg = QColor("#1a1a1a")   # マッチ文字色: 黒
        fm = painter.fontMetrics()

        x = text_rect.left() + 2
        y = text_rect.top()
        h = text_rect.height()
        baseline_y = y + (h + fm.ascent() - fm.descent()) // 2

        # 描画: 通常部分 → ハイライト部分 → ... を順に塗る
        last = 0
        for s, e in spans:
            # 直前の通常部分
            if s > last:
                seg = original_text[last:s]
                painter.setPen(fg)
                painter.drawText(x, baseline_y, seg)
                x += fm.horizontalAdvance(seg)
                if x > text_rect.right():
                    break
            # マッチ部分 (背景ベタ塗り + 太字)
            seg = original_text[s:e]
            w = fm.horizontalAdvance(seg)
            painter.fillRect(x, y, w, h, hl_bg)
            old_font = painter.font()
            bold_font = QFont(old_font)
            bold_font.setBold(True)
            painter.setFont(bold_font)
            painter.setPen(hl_fg)
            painter.drawText(x, baseline_y, seg)
            painter.setFont(old_font)
            x += w
            last = e
            if x > text_rect.right():
                break
        # 末尾の残り
        if last < len(original_text) and x <= text_rect.right():
            painter.setPen(fg)
            painter.drawText(x, baseline_y, original_text[last:])
        painter.restore()


class GrepPanel(QWidget):
    # ファイルパス, 行番号, マッチ行テキスト (リロード後にズレた場合の照合用)
    open_file_requested = pyqtSignal(str, int, str)
    close_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        self._file_items = {}
        # 検索条件 (start_search 時に更新される)
        self._search_pattern: str = ''
        self._case_sensitive: bool = False
        self._is_regex: bool = False
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # 1行目: フォルダ選択 (一番大事な「どこを検索するか」を最上段に)
        row_dir = QHBoxLayout()
        row_dir.setSpacing(4)
        row_dir.addWidget(QLabel("📁"))
        self.dir_input = QLineEdit()
        self.dir_input.setPlaceholderText("検索フォルダ (... ボタンで選択)")
        row_dir.addWidget(self.dir_input, 1)
        self.browse_btn = QPushButton("...")
        self.browse_btn.setFixedWidth(30)
        self.browse_btn.setToolTip("フォルダを参照")
        row_dir.addWidget(self.browse_btn)
        layout.addLayout(row_dir)

        # 2行目: 検索パターン + ファイル種別 + オプション + ボタン (全部1行に集約)
        row_search = QHBoxLayout()
        row_search.setSpacing(4)
        row_search.addWidget(QLabel("🔍"))
        self.pattern_input = QLineEdit()
        self.pattern_input.setPlaceholderText("検索パターン")
        row_search.addWidget(self.pattern_input, 3)

        # ファイル glob (コンパクトに)
        self.glob_input = QLineEdit("*")
        self.glob_input.setFixedWidth(90)
        self.glob_input.setPlaceholderText("*.log")
        self.glob_input.setToolTip("対象ファイルパターン (例: *.log, *.py)")
        row_search.addWidget(self.glob_input)

        # オプションをトグルボタン化 (チェックボックスより視覚的にスッキリ)
        self.case_check = QPushButton("Aa")
        self.case_check.setCheckable(True)
        self.case_check.setFixedWidth(34)
        self.case_check.setToolTip("大文字小文字を区別")
        self.regex_check = QPushButton(".*")
        self.regex_check.setCheckable(True)
        self.regex_check.setFixedWidth(34)
        self.regex_check.setToolTip("正規表現として扱う")
        toggle_style = (
            "QPushButton { background:#3a3a3a; color:#a9b7c6; border:1px solid #555;"
            "              padding:2px 4px; border-radius:3px; font-weight:600; }"
            "QPushButton:checked { background:#2a4a8a; color:#fff; border:1px solid #4a8eff; }"
            "QPushButton:hover { background:#4a4a4a; }"
            "QPushButton:checked:hover { background:#3a5a9a; }"
        )
        self.case_check.setStyleSheet(toggle_style)
        self.regex_check.setStyleSheet(toggle_style)
        row_search.addWidget(self.case_check)
        row_search.addWidget(self.regex_check)

        # メインアクション (緑強調)
        self.search_btn = QPushButton("▶ 検索")
        self.search_btn.setFixedWidth(72)
        self.search_btn.setStyleSheet(
            "QPushButton { background:#3a6e3a; color:#e0f0e0;"
            "              border:none; padding:3px 10px; border-radius:3px; font-weight:600; }"
            "QPushButton:hover { background:#4a8e4a; }"
            "QPushButton:disabled { background:#3a3a3a; color:#666; }"
        )
        row_search.addWidget(self.search_btn)
        self.stop_btn = QPushButton("■")
        self.stop_btn.setEnabled(False)
        self.stop_btn.setFixedWidth(30)
        self.stop_btn.setToolTip("検索を停止")
        row_search.addWidget(self.stop_btn)

        # 件数表示 (右端、控えめに)
        self.result_label = QLabel("")
        self.result_label.setStyleSheet("color:#9ED969; padding-left:8px; min-width:90px;")
        row_search.addWidget(self.result_label)

        # 閉じるボタン (Grepパネル自体を非表示にする)
        self.close_btn = QPushButton("✕")
        self.close_btn.setFixedWidth(28)
        self.close_btn.setToolTip("Grepパネルを閉じる (Esc)")
        self.close_btn.setStyleSheet(
            "QPushButton { background:#3a3a3a; color:#c0c0c0; border:1px solid #555;"
            "              padding:2px 4px; border-radius:3px; font-weight:600; }"
            "QPushButton:hover { background:#7a3a3a; color:#fff; border:1px solid #a55; }"
        )
        row_search.addWidget(self.close_btn)
        layout.addLayout(row_search)

        # 結果ツリー
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["ファイル / 行番号", "マッチ内容"])
        self.tree.setColumnWidth(0, 340)
        self.tree.setRootIsDecorated(True)
        # ジャンプ: ダブルクリック / Enter (activated) / シングルクリック の全てで対応
        # シングルクリック対応により VS Code 等と同じ感覚で素早く移動できる
        self.tree.itemDoubleClicked.connect(self._on_double_click)
        self.tree.itemActivated.connect(self._on_double_click)
        self.tree.itemClicked.connect(self._on_double_click)
        # マッチ箇所を黄色背景でハイライトするデリゲートを「マッチ内容」列に適用
        self._match_delegate = _GrepMatchDelegate(self.tree)
        self.tree.setItemDelegateForColumn(1, self._match_delegate)
        layout.addWidget(self.tree)

        self.setLayout(layout)

        self.browse_btn.clicked.connect(self._browse)
        self.search_btn.clicked.connect(self.start_search)
        self.stop_btn.clicked.connect(self._stop_search)
        self.pattern_input.returnPressed.connect(self.start_search)
        self.close_btn.clicked.connect(self.close_requested.emit)

        self.apply_theme()

    def apply_theme(self):
        """ボタン類をテーマ連動で再スタイル (検索ボタンの緑は維持)。"""
        t = _theme()
        toggle_style = (
            f"QPushButton {{ background:{t['control_bg']}; color:{t['text']};"
            f"              border:1px solid {t['border']};"
            f"              padding:2px 4px; border-radius:3px; font-weight:600; }}"
            f"QPushButton:hover {{ background:{t['control_hover']}; }}"
            f"QPushButton:checked {{ background:{t['selection']}; color:{t['text']};"
            f"              border:1px solid {t['selection']}; }}"
        )
        self.case_check.setStyleSheet(toggle_style)
        self.regex_check.setStyleSheet(toggle_style)
        self.close_btn.setStyleSheet(
            f"QPushButton {{ background:{t['control_bg']}; color:{t['text']};"
            f"              border:1px solid {t['border']};"
            f"              padding:2px 4px; border-radius:3px; font-weight:600; }}"
            f"QPushButton:hover {{ background:#c0392b; color:#fff; border:1px solid #e05545; }}"
        )

    def keyPressEvent(self, event):
        # Esc キーで Grep パネルを閉じる
        if event.key() == Qt.Key.Key_Escape:
            self.close_requested.emit()
            return
        super().keyPressEvent(event)

    def set_directory(self, path):
        if path:
            self.dir_input.setText(path)

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "フォルダを選択", self.dir_input.text())
        if d:
            self.dir_input.setText(d)

    def start_search(self):
        pattern = self.pattern_input.text().strip()
        directory = self.dir_input.text().strip()
        if not pattern:
            return
        if not directory or not os.path.isdir(directory):
            QMessageBox.warning(self, "エラー", "有効なフォルダを指定してください")
            return

        self._stop_search()
        self.tree.clear()
        self._file_items.clear()
        self.result_label.setText("検索中...")
        self.search_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

        # マッチハイライト用にデリゲートへ現在の検索条件を伝える
        self._match_delegate.set_pattern(
            pattern,
            self.case_check.isChecked(),
            self.regex_check.isChecked(),
        )
        # _on_result で行を切り詰める際に使うため、パネル側にも検索条件を保持
        self._search_pattern = pattern
        self._case_sensitive = self.case_check.isChecked()
        self._is_regex = self.regex_check.isChecked()

        self._worker = GrepWorker(
            directory, pattern,
            self.glob_input.text() or '*',
            self.case_check.isChecked(),
            self.regex_check.isChecked(),
        )
        self._worker.result_found.connect(self._on_result)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _stop_search(self):
        if self._worker and self._worker.isRunning():
            self._worker.stop()
            self._worker.wait()
        self.search_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

    # 表示用にマッチ周辺だけを切り出す長さ
    _TRIM_HEAD = 30   # マッチ前に確保するコンテキスト (文字数)
    _TRIM_TAIL = 200  # マッチ後に残す長さ

    def _trim_around_match(self, line: str) -> str:
        """長い行はマッチ箇所周辺だけを切り出して表示する。"""
        line = line.strip()
        if not self._search_pattern or len(line) < 200:
            return line
        # マッチ位置を取得
        match_start = -1
        match_end = -1
        try:
            if self._is_regex:
                flags = 0 if self._case_sensitive else re.IGNORECASE
                m = re.search(self._search_pattern, line, flags)
                if m and m.start() != m.end():
                    match_start, match_end = m.start(), m.end()
            else:
                hay = line if self._case_sensitive else line.lower()
                ndl = self._search_pattern if self._case_sensitive else self._search_pattern.lower()
                p = hay.find(ndl)
                if p >= 0:
                    match_start, match_end = p, p + len(ndl)
        except Exception:
            return line[: self._TRIM_HEAD + self._TRIM_TAIL]

        if match_start < 0:
            return line[: self._TRIM_HEAD + self._TRIM_TAIL]

        # マッチ前のコンテキスト
        if match_start > self._TRIM_HEAD:
            prefix = '… ' + line[match_start - self._TRIM_HEAD:match_start]
        else:
            prefix = line[:match_start]
        # マッチ後のコンテキスト
        tail_end = match_end + self._TRIM_TAIL
        if tail_end < len(line):
            suffix = line[match_end:tail_end] + ' …'
        else:
            suffix = line[match_end:]
        return prefix + line[match_start:match_end] + suffix

    def _on_result(self, filepath, lineno, line):
        if filepath not in self._file_items:
            item = QTreeWidgetItem(self.tree)
            item.setText(0, filepath)
            item.setForeground(0, QColor("#82AAFF"))
            f = item.font(0); f.setBold(True); item.setFont(0, f)
            item.setData(0, Qt.ItemDataRole.UserRole, ('file', filepath, 0, ''))
            self._file_items[filepath] = item

        parent = self._file_items[filepath]
        child = QTreeWidgetItem(parent)
        # ファイル名 (basename) を併記しておく事で、ファイルヘッダーがスクロール
        # で見えなくなっても「どのファイルの何行目か」が一目で分かるようにする
        basename = os.path.basename(filepath)
        child.setText(0, f"  {basename}: {lineno}")
        # 長い行はマッチ周辺だけを表示する (マッチ部分は必ず可視に)
        display_line = self._trim_around_match(line)
        child.setText(1, display_line)
        child.setForeground(0, QColor("#a0a0a0"))
        # ホバー時にフルパス + フルマッチ行をツールチップ表示 (切り詰めた中身もここで確認できる)
        tip = f"{filepath}\n行 {lineno}\n\n{line.rstrip()}"
        child.setToolTip(0, tip)
        child.setToolTip(1, tip)
        # マッチ行のテキストも保存 (ファイル更新で行番号がズレた時の照合用)
        # ジャンプ判定用なので 元の (切り詰めていない) 行 を保持する
        child.setData(0, Qt.ItemDataRole.UserRole, ('line', filepath, lineno, line.rstrip()))
        parent.setExpanded(True)

    def _on_finished(self, count):
        self.search_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        files = len(self._file_items)
        self.result_label.setText(f"{count} 件 / {files} ファイル")

    def _on_double_click(self, item, _col):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data and data[0] == 'line':
            filepath = data[1]
            lineno = data[2]
            line_text = data[3] if len(data) > 3 else ''
            self.open_file_requested.emit(filepath, lineno, line_text)


# ---------------------------------------------------------------------------
# エディタタブ（1ファイル）
# ---------------------------------------------------------------------------

LANG_MAP = {
    '.py': 'python', '.pyw': 'python',
    '.js': 'javascript', '.ts': 'javascript',
    '.jsx': 'javascript', '.tsx': 'javascript',
    '.mjs': 'javascript',
    '.sql': 'sql', '.ddl': 'sql', '.dml': 'sql',
    '.pls': 'sql', '.plsql': 'sql', '.pck': 'sql',
    '.prc': 'sql', '.fnc': 'sql', '.tps': 'sql', '.tpb': 'sql',
    '.log': 'log', '.LOG': 'log',
    # C / C++
    '.c': 'cpp', '.cpp': 'cpp', '.cc': 'cpp', '.cxx': 'cpp',
    '.h': 'cpp', '.hpp': 'cpp', '.hh': 'cpp', '.hxx': 'cpp', '.ino': 'cpp',
    # Java
    '.java': 'java',
    # C#
    '.cs': 'csharp',
    # Visual Basic 系 (VB6/VBA/VB.NET 共通でだいたい同じ色付け)
    '.vb': 'vb', '.bas': 'vb', '.cls': 'vb', '.frm': 'vb',
    '.vbs': 'vb', '.vba': 'vb',
    # XML / HTML
    '.xml': 'xml', '.html': 'xml', '.htm': 'xml', '.xhtml': 'xml',
    '.xsl': 'xml', '.xslt': 'xml', '.xsd': 'xml', '.svg': 'xml',
    '.csproj': 'xml', '.pom': 'xml',
    # VB プロジェクト系 (XML)
    '.vbproj': 'xml',
}

# 表示用 (UI のコンボ等で使う)
SUPPORTED_LANGUAGES = ['text', 'python', 'javascript', 'sql', 'log',
                       'cpp', 'java', 'csharp', 'vb', 'xml']


def detect_language(filename: str) -> str:
    """ファイル名から言語を推定。
    - 通常: 拡張子で LANG_MAP 引き
    - ローテーション済みログ (messvr.log.20260414 等) → 'log'
    - 圧縮ログ (.gz) は中身の拡張子で判定
    """
    name = filename.lower()
    # .gz は剥がして再判定
    if name.endswith('.gz'):
        name = name[:-3]
    ext = os.path.splitext(name)[1]
    lang = LANG_MAP.get(ext, 'text')
    if lang != 'text':
        return lang
    # 拡張子ヒットなし → ローテーション系の判定
    # 例: foo.log.20260414, foo.log.20260414104327, foo.log.1, foo.LOG.20...
    if '.log.' in name or name.endswith('.log'):
        return 'log'
    return 'text'


# ---------------------------------------------------------------------------
# 画像タブ (PNG/JPG/GIF/BMP/SVG 等を QPixmap で表示)
# ---------------------------------------------------------------------------
# 画像として扱う拡張子。SVG は Qt の image plugin が処理 (= ラスタライズ表示)。
_IMAGE_EXTS = {
    '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.ico',
    '.tif', '.tiff', '.svg',
}


def _is_image_path(path: str) -> bool:
    return os.path.splitext(path or '')[1].lower() in _IMAGE_EXTS


class ImageTab(QWidget):
    """画像ファイル表示用タブ。EditorTab と同じ filename / file_path 属性を持ち、
    上位 (タブ一覧 / 履歴 / FTP 既存タブ検索) で同等に扱えるようにする。
    編集機能は無いので is_modified は常に False。"""

    def __init__(self, path: str, filename: str):
        super().__init__()
        self.filename = filename
        self.file_path = path
        self.is_modified = False                  # 画像は編集不可
        self._pixmap = QPixmap(path) if path else QPixmap()
        self._zoom = 1.0

        layout = QVBoxLayout()
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)

        # 操作バー (フィット / 原寸 / 拡大 / 縮小 / 情報)
        bar = QHBoxLayout()
        self.fit_btn      = QPushButton("フィット")
        self.actual_btn   = QPushButton("原寸 100%")
        self.zoom_out_btn = QPushButton("➖")
        self.zoom_in_btn  = QPushButton("➕")
        self.zoom_label   = QLabel("100%")
        self.zoom_label.setMinimumWidth(48)
        self.info_label   = QLabel()
        for b in (self.fit_btn, self.actual_btn, self.zoom_out_btn,
                  self.zoom_in_btn):
            b.setAutoDefault(False)
            b.setMaximumHeight(24)
        bar.addWidget(self.fit_btn)
        bar.addWidget(self.actual_btn)
        bar.addWidget(self.zoom_out_btn)
        bar.addWidget(self.zoom_label)
        bar.addWidget(self.zoom_in_btn)
        bar.addStretch()
        bar.addWidget(self.info_label)
        layout.addLayout(bar)

        # 画像本体: QScrollArea + 中央配置の QLabel
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(False)     # 倍率に応じて手動 resize
        self.scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scroll.setWidget(self.image_label)
        layout.addWidget(self.scroll, 1)
        self.setLayout(layout)

        self.fit_btn.clicked.connect(self.fit_to_view)
        self.actual_btn.clicked.connect(self.actual_size)
        self.zoom_in_btn.clicked.connect(lambda: self._zoom_relative(1.25))
        self.zoom_out_btn.clicked.connect(lambda: self._zoom_relative(0.8))

        if self._pixmap.isNull():
            self.info_label.setText("画像を読み込めませんでした")
            self.image_label.setText("(画像を表示できません)")
            self.zoom_label.setText("--")
        else:
            self.actual_size()

    def _apply_zoom(self):
        if self._pixmap.isNull():
            return
        w = max(1, int(self._pixmap.width() * self._zoom))
        h = max(1, int(self._pixmap.height() * self._zoom))
        scaled = self._pixmap.scaled(
            w, h,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.image_label.setPixmap(scaled)
        self.image_label.resize(scaled.size())
        self.zoom_label.setText(f"{int(self._zoom * 100)}%")
        size = self._pixmap.size()
        self.info_label.setText(f"{size.width()} × {size.height()} px")

    def actual_size(self):
        self._zoom = 1.0
        self._apply_zoom()

    def fit_to_view(self):
        if self._pixmap.isNull():
            return
        vp = self.scroll.viewport().size()
        if vp.width() <= 0 or vp.height() <= 0:
            self._zoom = 1.0
        else:
            rw = vp.width()  / self._pixmap.width()
            rh = vp.height() / self._pixmap.height()
            self._zoom = max(min(rw, rh), 0.05)    # 縮小は許可、拡大上限は別途
        self._apply_zoom()

    def _zoom_relative(self, factor: float):
        self._zoom = max(0.05, min(self._zoom * factor, 20.0))
        self._apply_zoom()

    def wheelEvent(self, event):
        # Ctrl + ホイールでズーム (通常ホイールは縦スクロール)
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self._zoom_relative(1.1 if event.angleDelta().y() > 0 else 0.9)
            event.accept()
        else:
            super().wheelEvent(event)


# ---------------------------------------------------------------------------
# CSV/TSV をグリッド表示するタブ (閲覧専用、QTableView + QStandardItemModel)
# ---------------------------------------------------------------------------
_CSV_EXTS = {'.csv', '.tsv'}


def _is_csv_path(path: str) -> bool:
    return os.path.splitext(path or '')[1].lower() in _CSV_EXTS


class CsvTab(QWidget):
    """CSV/TSV をグリッド表示するタブ (閲覧専用)。
    EditorTab と同じ filename / file_path / is_modified / encoding 属性を持つ。
    編集・保存は実装せず、編集したい場合は「テキストとして開く」ボタンで
    EditorTab に切替える (MainWindow が処理)。
    """
    # 「テキストとして開き直して」と MainWindow に依頼するシグナル。
    open_as_text_requested = pyqtSignal(str)   # file_path

    def __init__(self, path: str, filename: str,
                 text_content: str, encoding: str):
        super().__init__()
        self.filename = filename
        self.file_path = path
        self.is_modified = False
        self.encoding = encoding
        self._raw_text = text_content
        # 区切り文字を最初の数行で自動判定 (Sniffer)。失敗時は拡張子で決める。
        self._delimiter = self._sniff_delimiter(text_content, path)
        # ヘッダ行数 (0 = ヘッダなし / 1 = 通常 / 2+ = 多段ヘッダを '/' 連結)
        self._header_rows = 1

        layout = QVBoxLayout()
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)

        # 操作バー
        bar = QHBoxLayout()
        self.delim_combo = QComboBox()
        self.delim_combo.addItems(['カンマ ,', 'タブ \\t', 'セミコロン ;', 'パイプ |'])
        self.delim_combo.setToolTip("区切り文字 (自動判定済み。手動切替可)")
        # QSpinBox は up/down ボタンが描画されない/押せない既知環境 (Qt6 +
        # 一部の Windows テーマ) があるので QComboBox にする。 選択肢が
        # 0..5 と固定数のため combo の方が確実。
        self.header_combo = QComboBox()
        self.header_combo.addItems(['0 (なし)', '1', '2', '3', '4', '5'])
        self.header_combo.setCurrentIndex(1)
        self.header_combo.setToolTip(
            "先頭から何行をヘッダ行として扱うか。\n"
            "0=ヘッダなし / 1=通常 / 2以上=多段ヘッダ ('/' で連結)"
        )
        self.header_combo.setFixedWidth(90)
        self.info_label = QLabel()
        self.info_label.setTextFormat(Qt.TextFormat.RichText)
        self.text_btn = QPushButton("📝 テキストとして開く")
        self.text_btn.setAutoDefault(False)
        self.text_btn.setToolTip("グリッドを閉じて EditorTab で開き直す")
        for w in (self.delim_combo, self.header_combo, self.text_btn):
            w.setMaximumHeight(26)
        bar.addWidget(QLabel("区切り:"))
        bar.addWidget(self.delim_combo)
        bar.addWidget(QLabel("ヘッダ行数:"))
        bar.addWidget(self.header_combo)
        bar.addStretch()
        bar.addWidget(self.info_label)
        bar.addWidget(self.text_btn)
        layout.addLayout(bar)

        # テーブル本体
        self.table = QTableView()
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(False)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_context_menu)
        # ヘッダはユーザーがリサイズできるが初回はサイズフィット
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive)
        self.table.verticalHeader().setDefaultSectionSize(
            self.fontMetrics().height() + 4)
        layout.addWidget(self.table, 1)
        self.setLayout(layout)

        # 初期表示 + 自動判定された区切り文字を combo に反映
        self._sync_delim_combo()
        self._rebuild_model()

        self.delim_combo.currentIndexChanged.connect(self._on_delim_changed)
        self.header_combo.currentIndexChanged.connect(self._on_header_rows_changed)
        self.text_btn.clicked.connect(
            lambda: self.open_as_text_requested.emit(self.file_path or ''))

    # ---- 区切り文字判定/同期 ----
    _DELIM_BY_INDEX = [',', '\t', ';', '|']

    @staticmethod
    def _sniff_delimiter(text: str, path: str) -> str:
        # 拡張子優先 (.tsv なら問答無用でタブ)
        ext = os.path.splitext(path or '')[1].lower()
        if ext == '.tsv':
            return '\t'
        # CRLF を LF に正規化してから判定 (Sniffer が \r を含む列頭で
        # 誤判定するのを防ぐ)
        sample = text[:8192].replace('\r\n', '\n').replace('\r', '\n')
        allowed = {',', '\t', ';', '|'}
        # まず先頭 1〜数行のヒューリスティック (各候補の出現数の最多)。
        # Sniffer よりこちらの方が日本語 CSV では当たることが多い。
        head_lines = [ln for ln in sample.split('\n')[:5] if ln]
        head = head_lines[0] if head_lines else ''
        counts = {d: head.count(d) for d in allowed}
        best_d, best_n = max(counts.items(), key=lambda kv: kv[1])
        if best_n > 0:
            return best_d
        # それでも 0 件なら csv.Sniffer に最後のチャンスを与える
        import csv as _csv
        try:
            dialect = _csv.Sniffer().sniff(sample, delimiters=',\t;|')
            if dialect.delimiter in allowed:
                return dialect.delimiter
        except Exception:
            pass
        return ','

    def _sync_delim_combo(self):
        try:
            i = self._DELIM_BY_INDEX.index(self._delimiter)
        except ValueError:
            i = 0
        self.delim_combo.blockSignals(True)
        self.delim_combo.setCurrentIndex(i)
        self.delim_combo.blockSignals(False)

    def _on_delim_changed(self, idx: int):
        if 0 <= idx < len(self._DELIM_BY_INDEX):
            self._delimiter = self._DELIM_BY_INDEX[idx]
            self._rebuild_model()

    def _on_header_rows_changed(self, n: int):
        self._header_rows = max(0, int(n))
        self._rebuild_model()

    # ---- モデル構築 ----
    def _rebuild_model(self):
        import csv as _csv
        # 改行を LF に正規化 + 行リストに分割してから csv.reader へ。
        # StringIO に CRLF をそのまま渡すと csv.reader が \r を末尾要素に
        # 含めて、結果として「1 セルに全部入る」見た目になることがある。
        text = self._raw_text.replace('\r\n', '\n').replace('\r', '\n')
        # splitlines は U+2028/2029 等も切るので line ending を完全吸収する
        lines = text.split('\n')
        # 末尾の空行 (= 末尾改行) は除外
        while lines and lines[-1] == '':
            lines.pop()
        try:
            reader = _csv.reader(lines, delimiter=self._delimiter)
            rows = list(reader)
        except Exception:
            rows = [[self._raw_text]]
        if not rows:
            rows = [['']]
        # 元の列数 (パディング前) を記録しておき、 後段で不一致行を検出する
        orig_counts = [len(r) for r in rows]
        # 列数の最大に揃える (短い行は空文字で右パディング)
        ncols = max(orig_counts) if orig_counts else 1
        rows = [r + [''] * (ncols - len(r)) for r in rows]

        # ヘッダ行数 N に応じて: rows[0..N) を列見出しに使い、 N>=2 は
        # 縦に並べて '/' 連結 (多段ヘッダ CSV 対応)。 N=0 は自動列名。
        n_header = min(self._header_rows, max(0, len(rows) - 1))
        if n_header >= 1:
            header_block = rows[:n_header]
            data_rows = rows[n_header:]
            data_orig_counts = orig_counts[n_header:]
            headers = []
            for c in range(ncols):
                parts = []
                for hr in header_block:
                    val = str(hr[c]).strip() if c < len(hr) else ''
                    if val and val not in parts:
                        parts.append(val)
                headers.append(' / '.join(parts) if parts else f"列{c+1}")
            # 期待列数 = ヘッダ 1 行目の元の列数 (パディング前)
            expected_cols = orig_counts[0]
        else:
            headers = [f"列{i+1}" for i in range(ncols)]
            data_rows = rows
            data_orig_counts = orig_counts
            # ヘッダ無し時は data 行で最も出現頻度が高い列数を期待値とする
            from collections import Counter as _Counter
            if data_orig_counts:
                expected_cols, _ = _Counter(data_orig_counts).most_common(1)[0]
            else:
                expected_cols = ncols

        # 不一致行 (パディング前の原列数が期待値と異なる) のインデックス
        mismatch_idx = {i for i, n in enumerate(data_orig_counts)
                        if n != expected_cols}

        model = QStandardItemModel(len(data_rows), ncols, self)
        model.setHorizontalHeaderLabels([str(h) for h in headers])
        # 縦ヘッダ (行番号) は 1-based に
        for r, row in enumerate(data_rows):
            for c, val in enumerate(row):
                item = QStandardItem(str(val))
                item.setEditable(False)
                model.setItem(r, c, item)
            # 不一致行の行ヘッダを赤くして、 ツールチップに何列だったか表示
            if r in mismatch_idx:
                cnt = data_orig_counts[r]
                model.setHeaderData(
                    r, Qt.Orientation.Vertical,
                    QColor('#E53935'),
                    Qt.ItemDataRole.ForegroundRole,
                )
                # ヘッダラベル末尾に ⚠ を付けて視認性を上げる
                model.setHeaderData(
                    r, Qt.Orientation.Vertical,
                    f"{r + 1} ⚠",
                    Qt.ItemDataRole.DisplayRole,
                )
                model.setHeaderData(
                    r, Qt.Orientation.Vertical,
                    f"列数不一致: {cnt} 列 (期待 {expected_cols} 列)",
                    Qt.ItemDataRole.ToolTipRole,
                )
        self.table.setModel(model)
        # 初回 / リビルド時に列幅をフィット (Interactive モードでは
        # 一度 resize すれば以後はユーザー操作で変更可能)
        self.table.resizeColumnsToContents()
        # 極端に広い列は読みにくいので上限を設ける
        for c in range(ncols):
            if self.table.columnWidth(c) > 400:
                self.table.setColumnWidth(c, 400)

        # 警告メッセージ部分は色分けして目立たせる
        n_bad = len(mismatch_idx)
        if n_bad:
            warn = (
                f"<span style='color:#E53935; font-weight:700;'>"
                f"⚠ {n_bad} 行が列数不一致 (期待 {expected_cols} 列)</span>"
            )
        else:
            warn = ''
        self.info_label.setText(
            f"{len(data_rows)} 行 × {ncols} 列    "
            f"[区切: {self._delimiter_label()} / ヘッダ {n_header} 行]"
            + (f"    {warn}" if warn else '')
        )

    def _delimiter_label(self) -> str:
        return {',': 'カンマ', '\t': 'タブ', ';': 'セミコロン', '|': 'パイプ'}.get(
            self._delimiter, repr(self._delimiter))

    # ---- 右クリックメニュー (コピー) ----
    def _on_context_menu(self, pos):
        menu = QMenu(self)
        act_cell = QAction("セルをコピー(&C)", self)
        act_cell.triggered.connect(self._copy_selection_cells)
        menu.addAction(act_cell)
        act_row  = QAction("選択行を TSV でコピー(&R)", self)
        act_row.triggered.connect(self._copy_selection_rows)
        menu.addAction(act_row)
        menu.addSeparator()
        act_all  = QAction("全行を TSV でコピー(&A)", self)
        act_all.triggered.connect(self._copy_all_tsv)
        menu.addAction(act_all)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _copy_selection_cells(self):
        sel = self.table.selectionModel()
        if sel is None:
            return
        cells = [idx.data() or '' for idx in sel.selectedIndexes()]
        QApplication.clipboard().setText('\n'.join(cells))

    def _copy_selection_rows(self):
        sel = self.table.selectionModel()
        if sel is None:
            return
        rows = sorted({idx.row() for idx in sel.selectedRows() or sel.selectedIndexes()})
        if not rows:
            return
        m = self.table.model()
        lines = []
        for r in rows:
            lines.append('\t'.join(
                str(m.index(r, c).data() or '') for c in range(m.columnCount())
            ))
        QApplication.clipboard().setText('\n'.join(lines))

    def _copy_all_tsv(self):
        m = self.table.model()
        if m is None:
            return
        lines = []
        headers = [m.headerData(c, Qt.Orientation.Horizontal) for c in range(m.columnCount())]
        lines.append('\t'.join(str(h or '') for h in headers))
        for r in range(m.rowCount()):
            lines.append('\t'.join(
                str(m.index(r, c).data() or '') for c in range(m.columnCount())
            ))
        QApplication.clipboard().setText('\n'.join(lines))


class EditorTab(QWidget):
    content_changed = pyqtSignal()

    def __init__(self, content='', filename='無題', file_path=None,
                 skip_initial_highlight=False,
                 disable_diff=False,
                 disable_undo=False):
        """
        skip_initial_highlight: True の場合、開いた直後の全行 rehighlight を
            スキップする。大ファイル時の UI フリーズ抑止。編集後のブロックは
            通常通り highlighter が反応するため、追記分は色が付く。
        disable_diff: True の場合、編集毎の差分計算 (変更ガター用 _update_change_map)
            を行わない。巨大ファイルでの unified_diff 重さ対策。
        disable_undo: True の場合、QTextDocument の undo 履歴を無効化。
            メモリ削減 (= スクロール時の重さも軽減) 。
        """
        super().__init__()
        self.filename = filename
        self.file_path = file_path
        self.is_modified = False
        # 検出されたエンコーディング。 load 時に _load_file から上書きされる。
        # 新規タブは _write_file が UTF-8 で保存するので UTF-8 をデフォルトに
        # しておく (ステータスバーに '—' が出ないように)。
        self.encoding = 'utf-8'

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        self.editor = CodeEditor()
        if disable_undo:
            self.editor.document().setUndoRedoEnabled(False)
        self._apply_editor_style()

        # コンテンツを先にセットしてからハイライターを接続する。
        # 逆順だと setPlainText 時にブロック状態が未初期化のまま
        # ハイライトが走り、ブロックコメント状態の引き継ぎが失敗する場合がある。
        if content:
            self.editor.setPlainText(content)
        # 差分判定の基準行は **setPlainText の後** に editor.toPlainText() から
        # 取得する。 Qt は改行 (\r\n→\n)、Unicode 行区切り (U+2028/2029)、
        # 末尾改行、NULL 文字などを内部正規化するため、入力 content から
        # 取得した splitlines と toPlainText 後の splitlines が
        # 1 行ずれることがある。ずれると _on_modified の防御層で
        # 「内容変わってない」判定が失敗し、 ● マーク誤検知 +
        # change_map が「全行 added」と判定して画面緑塗りになる。
        self._original_lines: list[str] = self.editor.toPlainText().splitlines()
        # 実編集トラッキング: contentsChange は (pos, removed, added) を渡す。
        # シンタックスハイライターの setFormat や Qt 内部の format dirty は
        # contentsChange を発火させないので、added/removed のどちらかが
        # 0 より大きい時のみ「ユーザが実際に編集した」と判定できる。
        # この方式なら modificationChanged の誤発火に依存せず確実に ● を制御できる。
        self._user_edited = False
        # reload_from_disk が setPlainText で内容差し替え中は contentsChange も
        # 発火するので、その間だけ trackerを無効化するためのガード。
        self._suppress_edit_tracking = False
        def _track_real_edit(_pos, removed, added):
            if self._suppress_edit_tracking:
                return
            if removed > 0 or added > 0:
                self._user_edited = True
        self.editor.document().contentsChange.connect(_track_real_edit)

        lang = detect_language(filename)
        self.highlighter = SyntaxHighlighter(self.editor.document(), lang)
        # document 接続直後の全行 rehighlight は、大ファイル時に
        # UI スレッドを数秒間ブロックするため skip オプションで抑止可能。
        if not skip_initial_highlight:
            self.highlighter.rehighlight()

        self.search_bar = InlineSearchBar(self.editor)

        layout.addWidget(self.search_bar)
        layout.addWidget(self.editor)
        self.setLayout(layout)

        # diff計算用デバウンスタイマー（300ms後に実行）
        self._diff_timer = QTimer()
        self._diff_timer.setSingleShot(True)
        self._diff_timer.setInterval(300)
        self._diff_timer.timeout.connect(self._update_change_map)

        self.editor.document().modificationChanged.connect(self._on_modified)
        # 巨大ファイル時は contentsChanged → diff 計算が重いので接続しない
        if not disable_diff:
            self.editor.document().contentsChanged.connect(self._diff_timer.start)
        # 初期 modified を確実にクリア。setPlainText で True になっていても、
        # ここで False を明示し、modificationChanged 経由で is_modified も
        # False に同期する (これがないと「ファイルを開いただけ / 検索だけで
        # 編集扱い」状態になり、終了時に未保存ダイアログが誤って出る)。
        self.editor.document().setModified(False)
        self.is_modified = False

    def reset_original(self):
        """保存後に基準行を更新してガターをクリアする"""
        self._original_lines = self.editor.toPlainText().splitlines()
        self.editor.set_change_map({})
        # 保存 = 「これが新しいベースライン」なので実編集フラグもクリア。
        # これ以降の編集だけが ● 対象になる。
        self._user_edited = False

    def reload_from_disk(self, new_content: str):
        """ディスクから再読込した内容で中身を差し替える (リロード専用パス) 。
        setPlainText は contentsChange + modificationChanged(True) を発火し、
        _track_real_edit が _user_edited=True にしてしまうため、
        差し替え中はガード変数 _suppress_edit_tracking を立てて吸収する。
        その後 _user_edited / _original_lines / modified flag を一括クリアする。
        """
        self._suppress_edit_tracking = True
        try:
            self.editor.setPlainText(new_content)
        finally:
            self._suppress_edit_tracking = False
        self._original_lines = self.editor.toPlainText().splitlines()
        self._user_edited = False
        self.editor.document().setModified(False)
        self.is_modified = False

    def _apply_editor_style(self):
        t = _theme()
        self.editor.setStyleSheet(f"""
            QPlainTextEdit {{
                background-color: {t['editor_bg']};
                color: {t['text']};
                border: none;
                selection-background-color: {t['selection']};
                /* 選択時の文字色を明示 — 未指定だと Qt が白を使い、Light
                   テーマで文字が脱色して読めなくなるため。
                   テキストの通常色をそのまま保持する。 */
                selection-color: {t['text']};
            }}
        """)

    def apply_settings(self):
        """テーマ・フォントサイズ変更を反映"""
        fs = SETTINGS.get('editor_font_size', 15)
        font = QFont("Consolas")
        font.setPixelSize(fs)   # px 指定 (設定ラベルの「px」と一致 / 段差を均一に)
        font.setFixedPitch(True)
        self.editor.setFont(font)
        self.editor.setTabStopDistance(
            4 * self.editor.fontMetrics().horizontalAdvance(' ')
        )
        self._apply_editor_style()
        # テーマ変更に合わせてシンタックス配色も作り直す
        if hasattr(self, 'highlighter') and hasattr(self.highlighter, 'rebuild_theme'):
            self.highlighter.rebuild_theme()
        # 検索バーにも UI フォントサイズを反映
        if hasattr(self, 'search_bar'):
            self.search_bar.apply_ui_settings()
        # 行番号エリアを再描画 (ガター色も theme 連動にしたい場合は CodeEditor を修正)
        self.editor.line_number_area.update()

    def _on_modified(self, modified):
        # modificationChanged は syntax highlighter / Qt 内部の format dirty 等で
        # 誤発火するため信頼できない。実編集の有無は _user_edited
        # (contentsChange で added/removed > 0 時のみ True) で判定する。
        # 「Qt は True にしたが実編集はゼロ」のケースは即 False に戻す。
        if modified and not self._user_edited:
            self.editor.document().setModified(False)
            return
        self.is_modified = bool(modified and self._user_edited)
        self.content_changed.emit()

    def _update_change_map(self):
        current_lines = self.editor.toPlainText().splitlines()
        change_map: dict[int, str] = {}

        matcher = difflib.SequenceMatcher(None, self._original_lines, current_lines, autojunk=False)
        for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
            if tag == 'insert':
                for ln in range(j1 + 1, j2 + 1):
                    change_map[ln] = 'added'
            elif tag == 'replace':
                for ln in range(j1 + 1, j2 + 1):
                    change_map[ln] = 'modified'
            elif tag == 'delete':
                # 削除位置は j1+1 行目の直前に表示
                target = j1 + 1
                if target not in change_map:
                    change_map[target] = 'deleted'

        self.editor.set_change_map(change_map)


# ---------------------------------------------------------------------------
# ソース参照の候補選択ダイアログ (ログ→ソースジャンプ)
# ---------------------------------------------------------------------------

class SourceRefPickerDialog(QDialog):
    """複数のソース参照 / 候補ファイルから1つを選んで開くためのダイアログ。
    entries: [{'ref': 参照dict, 'paths': [絶対パス, ...]}]
    選択結果は chosen() で (path, ref) を返す (キャンセル時 None)。
    """
    def __init__(self, entries: list[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle("ソースを開く — 候補選択")
        self.setMinimumWidth(560)
        self._results: list = []   # 開く対象の (path, ref) リスト

        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("開くソースファイルを選択してください (「全て開く」で全候補をタブで開く):"))

        self.list = QListWidget()
        for e in entries:
            ref = e['ref']
            line = int(ref.get('line') or 0)
            loc = f":{line}" if line > 0 else f"  ({ref.get('method','')} を検索)"
            paths = e.get('paths') or []
            if not paths:
                it = QListWidgetItem(f"{ref['raw']}    →  (見つかりません)")
                it.setForeground(QColor("#c0392b"))
                it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsSelectable
                            & ~Qt.ItemFlag.ItemIsEnabled)
                self.list.addItem(it)
                continue
            for p in paths:
                it = QListWidgetItem(f"{ref['raw']}  →  {p}{loc}")
                it.setData(Qt.ItemDataRole.UserRole, (p, ref))
                it.setToolTip(p)
                self.list.addItem(it)
        # 最初の選択可能項目を選んでおく
        for i in range(self.list.count()):
            if self.list.item(i).flags() & Qt.ItemFlag.ItemIsSelectable:
                self.list.setCurrentRow(i)
                break
        self.list.itemDoubleClicked.connect(lambda _it: self._accept_current())
        lay.addWidget(self.list)

        btns = QHBoxLayout()
        green = (
            "QPushButton{background:#3a6e3a;color:#e0f0e0;border:1px solid #4a8e4a;"
            "font-weight:600;padding:3px 14px;border-radius:2px;}"
            "QPushButton:hover{background:#4a8e4a;border:1px solid #5aa05a;}"
        )
        ok = QPushButton("開く")
        ok.setDefault(True)
        ok.setStyleSheet(green)
        self.open_all_btn = QPushButton("全て開く")
        self.open_all_btn.setToolTip("見つかった候補をすべてタブで開きます")
        cancel = QPushButton("キャンセル")
        ok.clicked.connect(self._accept_current)
        self.open_all_btn.clicked.connect(self._accept_all)
        cancel.clicked.connect(self.reject)
        btns.addWidget(self.open_all_btn)
        btns.addStretch(1)
        btns.addWidget(ok)
        btns.addWidget(cancel)
        lay.addLayout(btns)

    def _all_targets(self) -> list:
        """選択可能な全項目の (path, ref) を返す。"""
        out = []
        for i in range(self.list.count()):
            it = self.list.item(i)
            data = it.data(Qt.ItemDataRole.UserRole)
            if data:
                out.append(data)
        return out

    def _accept_current(self):
        it = self.list.currentItem()
        if it is None:
            return
        data = it.data(Qt.ItemDataRole.UserRole)
        if not data:
            return
        self._results = [data]
        self.accept()

    def _accept_all(self):
        targets = self._all_targets()
        if not targets:
            return
        self._results = targets
        self.accept()

    def results(self) -> list:
        """開く対象の (path, ref) リスト (キャンセル時は空)。"""
        return self._results

    def chosen(self):
        """後方互換: 先頭の (path, ref) を返す (無ければ None)。"""
        return self._results[0] if self._results else None


# ---------------------------------------------------------------------------
# 設定ダイアログ
# ---------------------------------------------------------------------------

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
        tabs.addTab(self._build_source_tab(), "ソース検索パス")
        tabs.addTab(self._build_migrate_tab(), "設定移行")
        lay.addWidget(tabs)

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
            QTabWidget::pane{{border:1px solid {t['border']};background:{t['panel_bg']};
                             top:-1px;}}
            QTabBar::tab{{background:{t['control_bg']};color:{t['text_dim']};
                         padding:5px 14px;border:1px solid {t['border']};
                         border-bottom:none;margin-right:2px;}}
            QTabBar::tab:selected{{background:{t['panel_bg']};color:{t['text']};
                                  border-bottom:1px solid {t['panel_bg']};}}
            QComboBox{{background:{t['control_bg']};color:{t['text']};
                      border:1px solid {t['border']};padding:2px 4px;min-height:24px;}}
            QComboBox QAbstractItemView{{background:{t['panel_bg']};color:{t['text']};
                                        selection-background-color:{t['selection']};}}
            QListWidget{{background:{t['panel_bg']};color:{t['text']};
                        border:1px solid {t['border']};}}
            QPushButton{{background:{t['control_bg']};color:{t['text']};border:none;
                        padding:4px 12px;border-radius:2px;}}
            QPushButton:hover{{background:{t['control_hover']};}}
            QPushButton:default{{background:{t['selection']};color:{t['text']};}}
        """)

    def _tab_page(self) -> tuple:
        """タブページ用の (QWidget, QVBoxLayout) を作る共通ヘルパー。"""
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(10, 10, 10, 10)
        v.setSpacing(6)
        return page, v

    def _build_display_tab(self) -> QWidget:
        page, v = self._tab_page()
        v.addWidget(self._section_label("フォントサイズ"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(2)
        self._spinners: dict[str, QSpinBox] = {}
        rows = [
            ("エディタ本文:", 'editor_font_size', 8, 28),
            ("UI (パネル等):", 'ui_font_size',    8, 20),
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

        v.addWidget(self._section_label("FTP ファイル一覧の時刻表示"))
        ftp_tz_row = QHBoxLayout()
        ftp_tz_row.addWidget(QLabel("方式:"))
        self.ftp_tz_combo = QComboBox()
        self.ftp_tz_combo.addItem("ローカル時刻に変換 (推奨 / FFFTP 互換)", 'local')
        self.ftp_tz_combo.addItem("サーバー値のまま表示", 'raw')
        cur_mode = SETTINGS.get('ftp_time_mode', 'local')
        for ix in range(self.ftp_tz_combo.count()):
            if self.ftp_tz_combo.itemData(ix) == cur_mode:
                self.ftp_tz_combo.setCurrentIndex(ix)
                break
        self.ftp_tz_combo.setToolTip(
            "ローカル時刻に変換 (推奨): LIST/MLSD のサーバー値を UTC と\n"
            "みなして OS の TZ に変換。 FFFTP の TZ=GMT 設定と同じ。\n\n"
            "サーバー値のまま表示: 変換せず生表示。 サーバーが既にローカル\n"
            "TZ で時刻を報告する環境向け。"
        )
        ftp_tz_row.addWidget(self.ftp_tz_combo, 1)
        v.addLayout(ftp_tz_row)
        v.addStretch()
        # このタブ (フォント・テーマ) のみをデフォルトに戻すボタン
        reset_row = QHBoxLayout()
        reset_row.addStretch()
        reset = QPushButton("デフォルトに戻す")
        reset.setToolTip("フォントサイズとテーマを初期値に戻します (ソース検索パス等には影響しません)")
        reset.clicked.connect(self._reset_defaults)
        reset_row.addWidget(reset)
        v.addLayout(reset_row)
        return page

    def _build_source_tab(self) -> QWidget:
        page, v = self._tab_page()
        src_help = QLabel(
            "ここに登録したフォルダを再帰検索し、ログの Class#method():行 や\n"
            "スタックトレースから該当ソースを開きます (右クリック → ソースを開く)。"
        )
        src_help.setStyleSheet("color:#888; font-size:10px; padding:2px 4px;")
        src_help.setWordWrap(True)
        v.addWidget(src_help)
        self.source_list = QListWidget()
        for d in (SETTINGS.get('source_dirs') or []):
            self.source_list.addItem(d)
        v.addWidget(self.source_list, 1)
        src_btns = QHBoxLayout()
        self.add_src_btn = QPushButton("＋ 追加")
        self.del_src_btn = QPushButton("－ 削除")
        self.add_src_btn.clicked.connect(self._add_source_dir)
        self.del_src_btn.clicked.connect(self._remove_source_dir)
        src_btns.addWidget(self.add_src_btn)
        src_btns.addWidget(self.del_src_btn)
        src_btns.addStretch()
        v.addLayout(src_btns)
        return page

    def _build_migrate_tab(self) -> QWidget:
        page, v = self._tab_page()
        migrate_help = QLabel(
            "FTPプロファイル / UI設定 / 検索履歴 を JSON 1ファイルに出力・読込できます。\n"
            "別 PC に環境を移したい時にお使いください。"
        )
        migrate_help.setStyleSheet("color:#888; font-size:10px; padding:2px 4px;")
        migrate_help.setWordWrap(True)
        v.addWidget(migrate_help)
        migrate_row = QHBoxLayout()
        self.export_btn = QPushButton("📤 エクスポート (JSON保存)")
        self.export_btn.setToolTip("FTPプロファイル / UI設定 / 検索履歴 を JSON に書き出す")
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
            f"border:1px solid {t['border']};border-right:none;padding:1px 4px;}}"
        )
        sp.setFixedSize(60, 22)

        btn_style = (
            f"QPushButton{{background:{t['control_bg']};color:{t['text']};"
            f"border:1px solid {t['border']};padding:0;margin:0;"
            f"font-size:10px;font-weight:bold;}}"
            f"QPushButton:hover{{background:{t['control_hover']};}}"
            f"QPushButton:pressed{{background:{t['selection']};color:{t['text']};}}"
        )
        up = QPushButton("△")
        up.setFixedSize(20, 22)
        up.setAutoRepeat(True)
        up.setAutoRepeatInterval(80)
        up.setStyleSheet(btn_style)
        up.clicked.connect(lambda: sp.stepBy(+1))
        down = QPushButton("▽")
        down.setFixedSize(20, 22)
        down.setAutoRepeat(True)
        down.setAutoRepeatInterval(80)
        down.setStyleSheet(btn_style)
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

    def _add_source_dir(self):
        d = QFileDialog.getExistingDirectory(self, "ソース検索パスを追加")
        if not d:
            return
        # 重複は追加しない
        existing = {self.source_list.item(i).text()
                    for i in range(self.source_list.count())}
        if d not in existing:
            self.source_list.addItem(d)

    def _remove_source_dir(self):
        for it in self.source_list.selectedItems():
            self.source_list.takeItem(self.source_list.row(it))

    def accept(self):
        for k, sp in self._spinners.items():
            SETTINGS[k] = sp.value()
        SETTINGS['theme'] = self.theme_combo.currentText()
        if hasattr(self, 'ftp_tz_combo'):
            mode = self.ftp_tz_combo.currentData()
            if mode in ('raw', 'local'):
                SETTINGS['ftp_time_mode'] = mode
        SETTINGS['source_dirs'] = [
            self.source_list.item(i).text()
            for i in range(self.source_list.count())
        ]
        try:
            _save_settings(SETTINGS)
        except Exception as e:
            QMessageBox.warning(self, "保存エラー", str(e))
        super().accept()


# ---------------------------------------------------------------------------
# メインウィンドウ
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Sora Editor  v{__version__}")
        self.setMinimumSize(800, 500)
        self.resize(1200, 800)

        # 起動元プロファイル名 (ssh_log_viewer から --profile で渡される)
        # DB実行ダイアログで「最初に選択する接続プロファイル」として使う
        self._origin_profile: str = ''

        # 外部ファイル変更検知
        self._fs_watcher = QFileSystemWatcher(self)
        self._fs_watcher.fileChanged.connect(self._on_external_change)
        # 自分で書き込んだ直後の自己イベントを無視するための集合
        self._self_write_paths: set[str] = set()
        self._self_write_clear_timer = QTimer(self)
        self._self_write_clear_timer.setSingleShot(True)
        self._self_write_clear_timer.timeout.connect(self._self_write_paths.clear)

        self._setup_ui()
        self._setup_menu()
        self._apply_theme()
        self.new_file()

    # --- UI構築 ---

    def _setup_ui(self):
        # 水平スプリッター：左=FTPパネル / 右=縦スプリッター
        self.splitter = QSplitter(Qt.Orientation.Horizontal)

        self.ftp_panel = FTPPanel()
        self.ftp_panel.setMinimumWidth(180)
        self.ftp_panel.setMaximumWidth(320)
        self.ftp_panel.file_downloaded.connect(self._open_ftp_content)
        self.ftp_panel.file_downloaded_path.connect(self._open_ftp_file)
        self.ftp_panel.download_starting.connect(self._mark_ftp_self_write)
        self.ftp_panel.set_modification_checker(self._is_local_file_modified)
        self.ftp_panel.hide()

        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.tabCloseRequested.connect(self._close_tab)
        self.tabs.currentChanged.connect(self._on_tab_changed)

        # 縦スプリッター：上=タブ / 下=Grep＆ブックマークパネル（横並び）
        self.v_splitter = QSplitter(Qt.Orientation.Vertical)

        self.grep_panel = GrepPanel()
        self.grep_panel.open_file_requested.connect(self._open_file_at_line)
        self.grep_panel.close_requested.connect(self._hide_grep_panel)
        self.grep_panel.hide()

        self.bookmark_panel = BookmarkPanel()
        self.bookmark_panel.jump_requested.connect(self._jump_to_bookmark)
        self.bookmark_panel.close_requested.connect(self._hide_bookmark_panel)
        self.bookmark_panel.bookmarks_cleared.connect(self._persist_all_bookmarks)
        self.bookmark_panel.hide()

        # 下部エリア (Grep 専用) — ブックマークは右サイドバーへ移動
        self.bottom_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.bottom_splitter.addWidget(self.grep_panel)
        self.bottom_splitter.hide()

        self.v_splitter.addWidget(self.tabs)
        self.v_splitter.addWidget(self.bottom_splitter)
        self.v_splitter.setStretchFactor(0, 3)
        self.v_splitter.setStretchFactor(1, 1)

        # ブックマークパネルは右サイドバー (縦長でリスト表示に向く)
        self.bookmark_panel.setMinimumWidth(240)

        self.splitter.addWidget(self.ftp_panel)
        self.splitter.addWidget(self.v_splitter)
        self.splitter.addWidget(self.bookmark_panel)
        self.splitter.setStretchFactor(0, 0)   # FTP: 固定気味
        self.splitter.setStretchFactor(1, 1)   # 中央(エディタ): 伸縮
        self.splitter.setStretchFactor(2, 0)   # ブックマーク: 固定気味
        self.setCentralWidget(self.splitter)

        # クイックアクセスツールバー (アイコンで主要機能を素早く起動)
        self._setup_toolbar()

        self.pos_label = QLabel("行: 1  列: 1")
        # 検出エンコーディング表示 (load 時に _update_encoding_label で更新)
        self.enc_label = QLabel("文字: —")
        self.enc_label.setToolTip("現在のタブで検出された文字コード")
        # 言語切替コンボ (ステータスバーで現在の言語を確認・変更)
        self.lang_combo = QComboBox()
        self.lang_combo.addItems(SUPPORTED_LANGUAGES)
        self.lang_combo.setToolTip("現在のタブのシンタックスハイライト言語")
        self.lang_combo.setFixedWidth(110)
        self.lang_combo.currentTextChanged.connect(self._on_language_changed)
        sb = QStatusBar()
        sb.addPermanentWidget(self.pos_label)
        sb.addPermanentWidget(self.enc_label)
        sb.addPermanentWidget(QLabel("言語:"))
        sb.addPermanentWidget(self.lang_combo)
        self.setStatusBar(sb)

    def _apply_toolbar_style(self):
        """クイックアクセスツールバーのスタイルをテーマ連動で適用。"""
        tb = getattr(self, '_toolbar', None)
        if tb is None:
            return
        t = _theme()
        fs = SETTINGS.get('ui_font_size', 10) + 3
        tb.setStyleSheet(
            f"QToolBar {{ background:{t['toolbar_bg']}; border:none;"
            f"           border-bottom:2px solid {t['border']};"
            f"           spacing:2px; padding:5px 4px; }}"
            f"QToolButton {{ background:transparent; color:{t['text']};"
            f"              border:1px solid transparent;"
            f"              padding:5px 9px; border-radius:3px; font-size:{fs}px; }}"
            f"QToolButton:hover {{ background:{t['control_hover']};"
            f"              border:1px solid {t['border']}; }}"
            f"QToolButton:checked {{ background:{t['selection']};"
            f"              border:1px solid {t['selection']}; }}"
            f"QToolBar::separator {{ background:{t['border']}; width:1px; margin:4px 6px; }}"
        )

    def _setup_toolbar(self):
        """主要機能のアイコンを並べたクイックアクセスツールバー。
        メニューを開かなくても FTPパネル切替・設定・SQL抽出・検索 などを
        ワンクリックで呼び出せる。
        """
        from PyQt6.QtWidgets import QToolBar
        tb = QToolBar("Quick Access")
        tb.setMovable(False)
        tb.setIconSize(QSize(18, 18))
        self._toolbar = tb
        # 上下に余白 + 下端に明確な境界線を引いてタブ領域と視覚的に分離 (テーマ連動)
        self._apply_toolbar_style()

        # ファイル操作 (よく使う 新規/開く/保存/名前を付けて保存)
        act_new = QAction("🆕 新規", self)
        act_new.setToolTip("新規ファイル (Ctrl+N)")
        act_new.triggered.connect(self.new_file)
        tb.addAction(act_new)

        act_open = QAction("📂 開く", self)
        act_open.setToolTip("ファイルを開く (Ctrl+O)")
        act_open.triggered.connect(self.open_file)
        tb.addAction(act_open)

        act_save = QAction("💾 保存", self)
        act_save.setToolTip("上書き保存 (Ctrl+S)")
        act_save.triggered.connect(self.save_file)
        tb.addAction(act_save)

        act_save_as = QAction("📝 名前を付けて保存", self)
        act_save_as.setToolTip("名前を付けて保存 (Ctrl+Shift+S)")
        act_save_as.triggered.connect(self.save_file_as)
        tb.addAction(act_save_as)

        tb.addSeparator()

        # FTP パネル トグル (チェック式)
        self._ftp_toolbar_action = QAction("📁 FTP", self)
        self._ftp_toolbar_action.setCheckable(True)
        self._ftp_toolbar_action.setToolTip("FTPパネルを表示/非表示 (Ctrl+T)")
        self._ftp_toolbar_action.triggered.connect(self._toggle_ftp)
        tb.addAction(self._ftp_toolbar_action)

        tb.addSeparator()

        # 検索 (トグル式)
        self._search_toolbar_action = QAction("🔍 検索", self)
        self._search_toolbar_action.setCheckable(True)
        self._search_toolbar_action.setToolTip("検索バーを表示/非表示 (Ctrl+F)")
        self._search_toolbar_action.triggered.connect(self._toggle_search_bar)
        tb.addAction(self._search_toolbar_action)

        # Grep (トグル式)
        self._grep_toolbar_action = QAction("🔎 Grep", self)
        self._grep_toolbar_action.setCheckable(True)
        self._grep_toolbar_action.setToolTip("Grep検索パネルを表示/非表示 (Ctrl+Shift+F)")
        self._grep_toolbar_action.triggered.connect(self._toggle_grep_panel)
        tb.addAction(self._grep_toolbar_action)

        # SQL抽出 (モーダル一発起動)
        act_sql = QAction("📋 SQL抽出", self)
        act_sql.setToolTip("ログからSQL抽出・整形 (Ctrl+Shift+Q)")
        act_sql.triggered.connect(self._show_sql_extract)
        tb.addAction(act_sql)

        tb.addSeparator()

        # ブックマーク一覧 (トグル式)
        self._bookmark_toolbar_action = QAction("🔖 ブックマーク", self)
        self._bookmark_toolbar_action.setCheckable(True)
        self._bookmark_toolbar_action.setToolTip("ブックマーク一覧を表示/非表示 (Ctrl+B)")
        self._bookmark_toolbar_action.triggered.connect(self._toggle_bookmark_panel)
        tb.addAction(self._bookmark_toolbar_action)

        # 右寄せのスペーサー
        spacer = QWidget()
        spacer.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        tb.addWidget(spacer)

        # 設定
        act_settings = QAction("⚙ 設定", self)
        act_settings.setToolTip("設定 (Ctrl+,)")
        act_settings.triggered.connect(self._open_settings)
        tb.addAction(act_settings)

        self.addToolBar(tb)

    def _setup_menu(self):
        mb = self.menuBar()

        # ファイルメニュー
        fm = mb.addMenu("ファイル(&F)")
        self._add_action(fm, "新規(&N)", QKeySequence.StandardKey.New, self.new_file)
        self._add_action(fm, "開く(&O)...", QKeySequence.StandardKey.Open, self.open_file)
        # 最近開いたファイル (動的に aboutToShow で再構築)
        self._recent_menu = fm.addMenu("最近開いたファイル(&R)")
        self._recent_menu.aboutToShow.connect(self._rebuild_recent_menu)
        fm.addSeparator()
        self._add_action(fm, "保存(&S)", QKeySequence.StandardKey.Save, self.save_file)
        self._add_action(fm, "名前を付けて保存(&A)...", QKeySequence("Ctrl+Shift+S"), self.save_file_as)
        self._add_action(fm, "全て保存(&L)", QKeySequence("Ctrl+Alt+S"), self.save_all)
        self._add_action(fm, "全て保存して終了(&X)", QKeySequence("Ctrl+Alt+Q"), self.save_all_and_exit)
        fm.addSeparator()
        # 設定 (Export/Import は設定ダイアログ内に統合)
        self._add_action(fm, "⚙ 設定(&P)...", QKeySequence("Ctrl+,"), self._open_settings)
        fm.addSeparator()
        self._add_action(fm, "終了(&Q)", QKeySequence("Ctrl+Q"), self.close)

        # 編集メニュー
        em = mb.addMenu("編集(&E)")
        # 元に戻す/やり直し/切り取り/コピー/貼り付けは QPlainTextEdit が
        # ネイティブで Ctrl+Z/Y/X/C/V を処理する。メニューアクションに同じ
        # ショートカットを設定すると「ambiguous shortcut」となり、やり直し等が
        # 発火しなくなるため、ここではショートカットを設定せず (ラベルにヒント表示のみ)
        # クリック動作だけを提供する。キーボードはエディタ内蔵処理に任せる。
        self._add_action(em, "元に戻す (Ctrl+Z)", None,
                         lambda: self.current_editor() and self.current_editor().undo())
        self._add_action(em, "やり直し (Ctrl+Y)", None,
                         lambda: self.current_editor() and self.current_editor().redo())
        em.addSeparator()
        self._add_action(em, "切り取り (Ctrl+X)", None,
                         lambda: self.current_editor() and self.current_editor().cut())
        self._add_action(em, "コピー (Ctrl+C)", None,
                         lambda: self.current_editor() and self.current_editor().copy())
        self._add_action(em, "貼り付け (Ctrl+V)", None,
                         lambda: self.current_editor() and self.current_editor().paste())
        em.addSeparator()
        self._add_action(em, "検索(&F)...", QKeySequence("Ctrl+F"), self._show_search)
        self._add_action(em, "検索・置換(&H)...", QKeySequence("Ctrl+H"), self._show_replace)
        self._add_action(em, "選択語を検索(Ctrl+F3)", QKeySequence("Ctrl+F3"), self._search_selection_next)
        self._add_action(em, "ファイル内Grep検索(&G)...", QKeySequence("Ctrl+Shift+F"), self._show_grep)
        em.addSeparator()
        self._add_action(em, "行へジャンプ(&L)...", QKeySequence("Ctrl+G"), self._show_goto_line)
        em.addSeparator()
        self._add_action(em, "次の変更箇所(&N)", QKeySequence("Alt+Down"), self._next_change)
        self._add_action(em, "前の変更箇所(&P)", QKeySequence("Alt+Up"), self._prev_change)

        # ブックマークメニュー
        bm = mb.addMenu("ブックマーク(&B)")
        self._add_action(bm, "ブックマーク登録/解除(&F2)", QKeySequence("F2"), self._toggle_bookmark)
        self._add_action(bm, "次のブックマーク(&F3)", QKeySequence("F3"), self._next_bookmark)
        self._add_action(bm, "前のブックマーク(Shift+F3)", QKeySequence("Shift+F3"), self._prev_bookmark)
        bm.addSeparator()
        self._add_action(bm, "次のエラー行(&E)", QKeySequence("Ctrl+E"), self._next_error)
        self._add_action(bm, "前のエラー行(Ctrl+Shift+E)", QKeySequence("Ctrl+Shift+E"), self._prev_error)
        bm.addSeparator()
        self._add_action(bm, "ブックマーク一覧(&L)", QKeySequence("Ctrl+B"), self._show_bookmarks)

        # 表示メニュー
        vm = mb.addMenu("表示(&V)")
        self._ftp_menu_action = QAction("FTPパネル(&T)", self)
        self._ftp_menu_action.setCheckable(True)
        self._ftp_menu_action.setShortcut(QKeySequence("Ctrl+T"))
        self._ftp_menu_action.triggered.connect(self._toggle_ftp)
        vm.addAction(self._ftp_menu_action)
        vm.addSeparator()
        # CSV のテキスト編集 ⇔ グリッド表示 トグル (現在のタブが CSV/TSV
        # ファイルの時だけ aboutToShow で有効化される)
        self._toggle_csv_view_action = QAction("📊 CSV グリッド表示に切替(&G)", self)
        self._toggle_csv_view_action.setShortcut(QKeySequence("F6"))
        self._toggle_csv_view_action.triggered.connect(self._toggle_csv_view)
        vm.addAction(self._toggle_csv_view_action)
        vm.aboutToShow.connect(self._sync_csv_view_action)
        # Grep パネルは編集メニュー側 (検索系) に既に登録済みのため
        # 表示メニューには置かない。チェック式と相性が悪く、検索バーとの
        # 排他切替で状態が同期しなくなる問題を防ぐ。

        # ツールメニュー (作業系の機能のみを残す)
        tm = mb.addMenu("ツール(&T)")
        self._add_action(tm, "ログからSQL抽出・整形(&S)...", QKeySequence("Ctrl+Shift+Q"), self._show_sql_extract)
        self._add_action(
            tm, "選択範囲からSQL抽出 (Ctrl+Shift+X)", QKeySequence("Ctrl+Shift+X"),
            self._show_sql_extract_selection,
        )

    def _open_settings(self):
        dlg = SettingsDialog(self)
        # 設定移行ボタンを MainWindow のメソッドに接続
        dlg.export_btn.clicked.connect(self._export_settings)
        dlg.import_btn.clicked.connect(self._import_settings)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._apply_all_settings()

    # ---------------------------------------------- 設定移行 (Export / Import)

    _MIGRATION_APP_KEY = "Sora Editor"
    _MIGRATION_SCHEMA = 1

    def _export_settings(self):
        """FTPプロファイル + UI設定 + 検索履歴 を JSON にエクスポート"""
        from datetime import datetime
        path, _ = QFileDialog.getSaveFileName(
            self, "設定をエクスポート",
            f"sora_settings_{datetime.now():%Y%m%d_%H%M%S}.json",
            "JSON (*.json);;すべて (*)",
        )
        if not path:
            return
        bundle = {
            "schema_version": self._MIGRATION_SCHEMA,
            "app": self._MIGRATION_APP_KEY,
            "version": __version__,
            "exported_at": datetime.now().isoformat(timespec='seconds'),
            "ftp_profiles": load_profiles(),
            "settings":     dict(SETTINGS),
            "history":      dict(SEARCH_HISTORY),
        }
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(bundle, f, ensure_ascii=False, indent=2)
            self.statusBar().showMessage(
                f"📤 エクスポート完了 → {os.path.basename(path)}", 4000
            )
        except Exception as e:
            QMessageBox.critical(self, "エクスポートエラー", str(e))

    def _import_settings(self):
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

        ftp_profiles = bundle.get('ftp_profiles', {})
        settings     = bundle.get('settings', {})
        history      = bundle.get('history', {})

        cur_ftp = load_profiles()
        msg = (
            f"インポートします:\n"
            f"・FTPプロファイル: {len(ftp_profiles)}件 (現在 {len(cur_ftp)}件)\n"
            f"・UI設定: {len(settings)}項目\n"
            f"・検索/置換履歴: 検索{len(history.get('search', []))} / "
            f"置換{len(history.get('replace', []))}\n\n"
            "「Yes」=マージ / 「No」=置換 / 「Cancel」=中止"
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
            new_ftp = {**cur_ftp, **ftp_profiles}
        else:
            new_ftp = dict(ftp_profiles)

        try:
            save_profiles(new_ftp)
            for k, v in settings.items():
                if k in _DEFAULT_SETTINGS:
                    SETTINGS[k] = v
            _save_settings(SETTINGS)
            # 検索履歴も統合
            if history:
                for key in ('search', 'replace'):
                    incoming = history.get(key, [])
                    if ans == QMessageBox.StandardButton.Yes:
                        # 重複排除して結合
                        merged = list(dict.fromkeys(incoming + SEARCH_HISTORY.get(key, [])))
                        SEARCH_HISTORY[key] = merged[:_HISTORY_MAX]
                    else:
                        SEARCH_HISTORY[key] = incoming[:_HISTORY_MAX]
                _save_search_history()
        except Exception as e:
            QMessageBox.critical(self, "保存エラー", str(e))
            return

        self._apply_all_settings()
        self.statusBar().showMessage(
            f"📥 インポート完了: FTPプロファイル {len(new_ftp)}件", 4000
        )

    def _apply_all_settings(self):
        """テーマ・フォントサイズの変更を全UIに反映"""
        self._apply_theme()
        # 各タブにも適用
        for i in range(self.tabs.count()):
            tab = self.tabs.widget(i)
            if hasattr(tab, 'apply_settings'):
                tab.apply_settings()
        # サイドパネル群
        for panel in (self.ftp_panel, self.grep_panel, self.bookmark_panel):
            if hasattr(panel, 'apply_settings'):
                panel.apply_settings()

    def _add_action(self, menu, label, shortcut, slot):
        act = QAction(label, self)
        # shortcut=None ならショートカット未設定 (ネイティブ処理に任せる/競合回避)
        if shortcut is not None:
            if isinstance(shortcut, QKeySequence.StandardKey):
                act.setShortcut(QKeySequence(shortcut))
            else:
                act.setShortcut(shortcut)
        act.triggered.connect(slot)
        menu.addAction(act)

    def _rebuild_recent_menu(self):
        """「最近開いたファイル」サブメニューを最新の履歴で再構築。
        メニュー展開時に毎回呼ばれるので、開きながら別タブで開いた履歴も反映できる。"""
        menu = self._recent_menu
        menu.clear()
        items = _load_recent_files()
        if not items:
            act = QAction("(履歴なし)", self)
            act.setEnabled(False)
            menu.addAction(act)
            return
        for i, path in enumerate(items, 1):
            # 表示は ファイル名 + フルパス (略式)。先頭 9 件にはアクセラレータ &1..&9。
            base = os.path.basename(path) or path
            prefix = f"&{i} " if i < 10 else "   "
            label = f"{prefix}{base}    [{path}]"
            act = QAction(label, self)
            act.setToolTip(path)
            act.triggered.connect(lambda _checked=False, p=path: self._open_recent(p))
            menu.addAction(act)
        menu.addSeparator()
        clear_act = QAction("履歴をクリア(&C)", self)
        clear_act.triggered.connect(self._clear_recent_files)
        menu.addAction(clear_act)

    def _open_recent(self, path: str):
        """履歴項目クリック → 既存タブがあればアクティブ化、無ければ _load_file。
        ファイルが存在しなければ警告 + 履歴から除去。"""
        if not os.path.isfile(path):
            QMessageBox.warning(self, "ファイルが見つかりません",
                                f"履歴のファイルが存在しません:\n{path}\n履歴から除外します。")
            items = [p for p in _load_recent_files()
                     if os.path.normcase(p) != os.path.normcase(path)]
            _save_recent_files(items)
            return
        # 既存タブ確認
        target = os.path.normcase(os.path.abspath(path))
        for i in range(self.tabs.count()):
            t = self.tabs.widget(i)
            if isinstance(t, EditorTab) and t.file_path:
                if os.path.normcase(os.path.abspath(t.file_path)) == target:
                    self.tabs.setCurrentIndex(i)
                    return
        self._load_file(path)

    def _clear_recent_files(self):
        _save_recent_files([])

    def _apply_theme(self):
        t = _theme()
        ui_fs = SETTINGS.get('ui_font_size', 10)
        self.setStyleSheet(f"""
            QMainWindow {{ background: {t['bg']}; }}
            QMenuBar {{ background: {t['toolbar_bg']}; color: {t['text']}; padding: 0; margin: 0; }}
            QMenuBar::item {{ padding: 3px 8px; }}
            QMenuBar::item:selected {{ background: {t['control_hover']}; }}
            QMenu {{ background: {t['panel_bg']}; color: {t['text']};
                     border: 1px solid {t['border']}; }}
            QMenu::item {{ padding: 3px 20px 3px 12px; }}
            QMenu::item:selected {{ background: {t['selection']}; }}
            QTabWidget::pane {{ border: none; background: {t['editor_bg']};
                                margin-top: 2px; }}
            QTabBar {{ background: {t['toolbar_bg']}; }}
            QTabBar::tab {{
                background: {t['control_bg']}; color: {t['text']};
                padding: 6px 14px; border: none; min-width: 70px;
                margin-right: 2px; margin-top: 3px;
                font-size: {ui_fs}px;
            }}
            QTabBar::tab:selected {{
                background: {t['editor_bg']}; color: {t['text']};
                border-top: 2px solid {t['selection']};
            }}
            QTabBar::tab:hover {{ background: {t['control_hover']}; }}
            QTabBar::close-button {{ subcontrol-position: right; }}
            QStatusBar {{ background: {t['toolbar_bg']}; color: {t['text']}; padding: 0;
                         font-size: {ui_fs}px; }}
            QStatusBar::item {{ border: none; }}
            QPushButton {{
                background: {t['control_bg']}; color: {t['text']};
                border: none; padding: 2px 8px; border-radius: 2px;
            }}
            QPushButton:hover {{ background: {t['control_hover']}; }}
            QPushButton:disabled {{ color: {t['text_dim']}; }}
            QLineEdit {{
                background: {t['panel_bg']}; color: {t['text']};
                border: 1px solid {t['border']}; padding: 1px 3px;
                font-size: {ui_fs}px;
            }}
            QCheckBox {{ color: {t['text']}; spacing: 4px; }}
            QLabel {{ color: {t['text']}; }}
            QDialog {{ background: {t['bg']}; }}
            QSplitter::handle {{ background: {t['border']}; }}
            QSplitter::handle:horizontal {{ width: 2px; }}
            QSplitter::handle:vertical   {{ height: 2px; }}
            QListWidget {{
                background: {t['panel_bg']}; color: {t['text']}; border: none;
                font-size: {ui_fs}px;
            }}
            QListWidget::item {{ padding: 1px 2px; }}
            QListWidget::item:selected {{ background: {t['selection']}; color: {t['text']}; }}
            QListWidget::item:hover {{ background: {t['control_hover']}; }}
            QTreeWidget {{
                background: {t['panel_bg']}; color: {t['text']}; border: none;
                outline: none; font-size: {ui_fs}px;
            }}
            QTreeWidget::item {{ padding: 1px 0; }}
            QTreeWidget::item:selected {{ background: {t['selection']}; color: {t['text']}; }}
            QTreeWidget::item:hover {{ background: {t['control_hover']}; }}
            QTableView {{
                background: {t['editor_bg']}; color: {t['text']};
                gridline-color: {t['border']};
                alternate-background-color: {t['panel_bg']};
                selection-background-color: {t['selection']};
                selection-color: {t['text']};
                border: 1px solid {t['border']};
            }}
            QTableView::item:selected {{ background: {t['selection']}; color: {t['text']}; }}
            QHeaderView::section {{
                background: {t['control_bg']}; color: {t['text']};
                border: none; padding: 2px 4px;
            }}
            QComboBox {{
                background: {t['control_bg']}; color: {t['text']};
                border: 1px solid {t['border']}; padding: 1px 3px;
                font-size: {ui_fs}px;
            }}
            QComboBox::drop-down {{ border: none; width: 16px; }}
            QComboBox QAbstractItemView {{
                background: {t['panel_bg']}; color: {t['text']};
                selection-background-color: {t['selection']};
            }}
            QSpinBox {{
                background: {t['control_bg']}; color: {t['text']};
                border: 1px solid {t['border']}; padding: 1px 3px;
            }}
            QGroupBox {{ color: {t['text']}; border: 1px solid {t['border']};
                        margin-top: 6px; padding-top: 4px; }}
            QToolTip {{ background-color: {t['panel_bg']}; color: {t['text']};
                       border: 1px solid {t['border']}; padding: 3px 6px;
                       opacity: 240; }}
            QPlainTextEdit, QTextEdit {{
                background: {t['editor_bg']}; color: {t['text']};
                selection-background-color: {t['selection']};
                border: none;
            }}
            /* スクロールバー */
            QScrollBar:vertical {{
                background: {t['panel_bg']}; width: 12px; border: none; margin: 0;
            }}
            QScrollBar::handle:vertical {{
                background: {t['control_bg']}; border-radius: 4px;
                min-height: 30px; margin: 2px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {t['control_hover']};
            }}
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {{ height: 0; width: 0; }}
            QScrollBar::add-page:vertical,
            QScrollBar::sub-page:vertical {{ background: none; }}
            QScrollBar:horizontal {{
                background: {t['panel_bg']}; height: 12px; border: none; margin: 0;
            }}
            QScrollBar::handle:horizontal {{
                background: {t['control_bg']}; border-radius: 4px;
                min-width: 30px; margin: 2px;
            }}
            QScrollBar::handle:horizontal:hover {{
                background: {t['control_hover']};
            }}
            QScrollBar::add-line:horizontal,
            QScrollBar::sub-line:horizontal {{ height: 0; width: 0; }}
            QScrollBar::add-page:horizontal,
            QScrollBar::sub-page:horizontal {{ background: none; }}
        """)
        # ツールバー・各パネルもテーマ連動で再スタイル
        self._apply_toolbar_style()
        if hasattr(self, 'bookmark_panel'):
            self.bookmark_panel.apply_theme()
        if hasattr(self, 'grep_panel') and hasattr(self.grep_panel, 'apply_theme'):
            self.grep_panel.apply_theme()
        if hasattr(self, 'ftp_panel') and hasattr(self.ftp_panel, 'apply_theme'):
            self.ftp_panel.apply_theme()

    # --- タブ操作 ---

    def current_tab(self):
        w = self.tabs.currentWidget()
        return w if isinstance(w, EditorTab) else None

    def current_editor(self):
        tab = self.current_tab()
        return tab.editor if tab else None

    def new_file(self):
        tab = EditorTab()
        self._connect_tab(tab)
        idx = self.tabs.addTab(tab, "無題")
        self.tabs.setCurrentIndex(idx)

    def open_file(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "ファイルを開く", "",
            "すべてのファイル (*);;"
            "Pythonファイル (*.py *.pyw);;"
            "JavaScriptファイル (*.js *.ts *.jsx *.tsx);;"
            "テキストファイル (*.txt *.md);;"
            "CSV/TSV (*.csv *.tsv);;"
            "画像ファイル (*.png *.jpg *.jpeg *.gif *.bmp *.webp *.svg *.ico *.tif *.tiff)",
        )
        for path in paths:
            self._load_file(path)

    # 大ファイルしきい値
    _LARGE_FILE_SIZE = 2_000_000    # 2MB: シンタックスハイライト初期 rehighlight をスキップ
    _HUGE_FILE_SIZE  = 10_000_000   # 10MB: diff/undo も無効化

    @staticmethod
    def _detect_text_encoding(path: str) -> tuple[str, str]:
        """ファイルをエンコーディング自動判定で読み込み (内容, 検出エンコ名) を返す。
        UTF-8 → UTF-8-SIG (BOM) → CP932 (Windows-31J, Shift_JIS) → EUC-JP の
        順に strict で試し、最初に成功したエンコーディングで返す。
        全部失敗したら最後の手段として UTF-8 errors='replace' (エンコ名は
        'UTF-8 (replace)' とする)。
        Windows + Excel 由来の日本語 CSV は CP932 が多い。
        """
        with open(path, 'rb') as f:
            raw = f.read()
        for enc in ('utf-8-sig', 'utf-8', 'cp932', 'shift_jis', 'euc-jp'):
            try:
                return raw.decode(enc), enc
            except UnicodeDecodeError:
                continue
        return raw.decode('utf-8', errors='replace'), 'UTF-8 (replace)'

    @classmethod
    def _read_text_auto_encoding(cls, path: str) -> str:
        """互換: 内容のみを返す。"""
        return cls._detect_text_encoding(path)[0]

    def _load_file(self, path):
        try:
            try:
                size = os.path.getsize(path)
            except Exception:
                size = 0
            filename = os.path.basename(path)
            # 画像ファイルは ImageTab で開く (EditorTab とは別系統)。
            # _connect_tab / _restore_tab_bookmarks / _read_text_auto_encoding は
            # 編集タブ専用なので呼ばない。 _watch_path と履歴登録だけ行う。
            if _is_image_path(path):
                tab = ImageTab(path, filename)
                idx = self.tabs.addTab(tab, f"🖼 {filename}")
                self.tabs.setCurrentIndex(idx)
                self._watch_path(path)
                _push_recent_file(path)
                return
            content, enc = self._detect_text_encoding(path)
            # CSV/TSV はグリッド表示 (CsvTab) で開く。
            # 「テキストとして開き直す」は CsvTab のシグナル経由。
            if _is_csv_path(path):
                tab = CsvTab(path, filename, content, enc)
                tab.open_as_text_requested.connect(
                    lambda p, _t=tab: self._reopen_csv_as_text(_t, p))
                idx = self.tabs.addTab(tab, f"📊 {filename}")
                self.tabs.setCurrentIndex(idx)
                self._watch_path(path)
                _push_recent_file(path)
                self._update_encoding_label()
                return
            # 大ファイル時は UI フリーズ要因 (rehighlight / diff / undo) を抑制
            skip_hl = size >= self._LARGE_FILE_SIZE
            huge    = size >= self._HUGE_FILE_SIZE
            tab = EditorTab(
                content, filename, path,
                skip_initial_highlight=skip_hl,
                disable_diff=huge,
                disable_undo=huge,
            )
            tab.encoding = enc
            self._connect_tab(tab)
            idx = self.tabs.addTab(tab, filename)
            self.tabs.setCurrentIndex(idx)
            tab.editor.document().setModified(False)
            self._restore_tab_bookmarks(tab)
            self._watch_path(path)
            _push_recent_file(path)
            self._update_encoding_label()
            if skip_hl:
                mb = size / (1024 * 1024)
                msg = (
                    f"大ファイル ({mb:.1f} MB) のためシンタックスハイライトを抑制しました。"
                    if not huge else
                    f"巨大ファイル ({mb:.1f} MB) — ハイライト/差分/undo を全て抑制しました。"
                )
                self.statusBar().showMessage(msg, 6000)
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"ファイルを開けませんでした:\n{e}")

    def _open_ftp_content(self, content, filename):
        tab = EditorTab(content, filename)
        self._connect_tab(tab)
        idx = self.tabs.addTab(tab, f"[FTP] {filename}")
        self.tabs.setCurrentIndex(idx)

    def _open_ftp_file(self, local_path, filename):
        """FTP でダウンロードしたファイルを一時ファイル経由で開く。
        同パスのタブが既に開いていたら、そのタブを最新内容に置換 (リロード)。"""
        try:
            size = os.path.getsize(local_path)
        except Exception:
            size = 0
        # 画像ファイルはテキスト読み込みをスキップして ImageTab に直接渡す。
        # 既存タブが画像タブなら一旦閉じて開き直すのが最も単純 (QPixmap 差替よりも
        # コードパスが一本化できる)。
        if _is_image_path(local_path):
            for i in range(self.tabs.count()):
                t = self.tabs.widget(i)
                if hasattr(t, 'file_path') and t.file_path == local_path:
                    self.tabs.removeTab(i)
                    t.deleteLater()
                    break
            tab = ImageTab(local_path, filename)
            idx = self.tabs.addTab(tab, f"🖼 [FTP] {filename}")
            self.tabs.setCurrentIndex(idx)
            self._watch_path(local_path)
            _push_recent_file(local_path)
            self.statusBar().showMessage(
                f"[FTP] {filename} を画像として開きました", 3000
            )
            return
        try:
            content, enc = self._detect_text_encoding(local_path)
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"ファイルを開けませんでした:\n{e}")
            return

        # 既存タブ検索
        existing_idx = -1
        for i in range(self.tabs.count()):
            t = self.tabs.widget(i)
            if hasattr(t, 'file_path') and t.file_path == local_path:
                existing_idx = i
                break

        if existing_idx >= 0:
            # 既存タブをリロード (未保存編集はFTPPanel側で上書き確認済みなのでここでは破棄)
            # reload_from_disk が setPlainText + _user_edited クリア + ● 解除を
            # 一括処理する。大ファイル時は rehighlight() を **呼ばない**
            # (= 遅延ハイライト任せ) でメインスレッドのブロックを避ける。
            tab = self.tabs.widget(existing_idx)
            cur_block = tab.editor.textCursor().blockNumber()
            tab.reload_from_disk(content)
            tab.encoding = enc
            if size < self._LARGE_FILE_SIZE:
                tab.highlighter.rehighlight()
            # スクロール位置を元の行に近づける
            self._jump_to_line(tab.editor, cur_block + 1)
            self.tabs.setCurrentIndex(existing_idx)
            self._update_encoding_label()
            self.statusBar().showMessage(
                f"[FTP] {filename} をリロードしました", 3000
            )
            return

        # 新規タブ (大ファイル抑制を _load_file と一致させる)
        skip_hl = size >= self._LARGE_FILE_SIZE
        huge    = size >= self._HUGE_FILE_SIZE
        tab = EditorTab(
            content, filename, local_path,
            skip_initial_highlight=skip_hl,
            disable_diff=huge,
            disable_undo=huge,
        )
        tab.encoding = enc
        self._connect_tab(tab)
        idx = self.tabs.addTab(tab, f"[FTP] {filename}")
        self.tabs.setCurrentIndex(idx)
        tab.editor.document().setModified(False)
        self._restore_tab_bookmarks(tab)
        self._watch_path(local_path)
        _push_recent_file(local_path)
        self._update_encoding_label()

    def _is_local_file_modified(self, local_path: str) -> bool:
        """指定ローカルパスに紐づくタブで未保存編集があるか"""
        for i in range(self.tabs.count()):
            t = self.tabs.widget(i)
            if hasattr(t, 'file_path') and t.file_path == local_path:
                try:
                    if t.editor.document().isModified():
                        return True
                except Exception:
                    pass
        return False

    def _connect_tab(self, tab):
        tab.content_changed.connect(self._on_content_changed)
        tab.editor.cursorPositionChanged.connect(self._update_cursor)
        # ブックマーク変更 → 一覧更新 + ファイル単位で永続化
        tab.editor.bookmark_toggled.connect(
            lambda *_: self._on_bookmark_changed(tab))
        # 右クリック「選択範囲からSQL抽出」
        tab.editor.sql_extract_requested.connect(self._show_sql_extract_selection)
        # 右クリック「ソースを開く (該当行へジャンプ)」
        tab.editor.source_open_requested.connect(self._open_source_from_selection)

    # ------------------------------------------------ ブックマーク永続化
    @staticmethod
    def _bm_key(path: str) -> str:
        try:
            return os.path.normcase(os.path.abspath(path))
        except Exception:
            return path

    def _on_bookmark_changed(self, tab):
        self._refresh_bookmarks()
        self._persist_tab_bookmarks(tab)

    def _persist_tab_bookmarks(self, tab):
        """タブのブックマークをファイルパス単位で JSON 保存。
        パスの無いタブ (新規/未保存) は保存対象外。"""
        path = getattr(tab, 'file_path', None)
        if not path:
            return
        store = _load_bookmarks_store()
        key = self._bm_key(path)
        bms = sorted(getattr(tab.editor, '_bookmarks', set()))
        if bms:
            store[key] = bms
        else:
            store.pop(key, None)   # 全解除されたら記録も消す
        _save_bookmarks_store(store)

    def _restore_tab_bookmarks(self, tab):
        """保存済みブックマークをタブへ復元 (ファイルを開いた直後に呼ぶ)。"""
        path = getattr(tab, 'file_path', None)
        if not path:
            return
        bms = _load_bookmarks_store().get(self._bm_key(path)) or []
        if not bms:
            return
        total = tab.editor.document().blockCount()
        for ln in bms:
            if isinstance(ln, int) and 1 <= ln <= total:
                tab.editor._bookmarks.add(ln)
        tab.editor.line_number_area.update()
        self._refresh_bookmarks()

    def _persist_all_bookmarks(self):
        """全タブのブックマークを保存 (全削除後などに使用)。"""
        for i in range(self.tabs.count()):
            t = self.tabs.widget(i)
            if isinstance(t, EditorTab):
                self._persist_tab_bookmarks(t)

    def save_file(self):
        tab = self.current_tab()
        if not tab:
            return
        if tab.file_path:
            self._write_file(tab, tab.file_path)
        else:
            self.save_file_as()

    # 名前を付けて保存の拡張子フィルタ (代表的なもの)
    _SAVE_FILTERS = (
        "テキストファイル (*.txt);;"
        "ログファイル (*.log);;"
        "SQLファイル (*.sql);;"
        "Pythonファイル (*.py);;"
        "JavaScript (*.js);;"
        "JSON (*.json);;"
        "CSV (*.csv);;"
        "Markdown (*.md);;"
        "XML (*.xml);;"
        "HTML (*.html *.htm);;"
        "YAML (*.yaml *.yml);;"
        "シェルスクリプト (*.sh);;"
        "設定ファイル (*.ini *.conf *.cfg);;"
        "すべてのファイル (*)"
    )

    # 拡張子 → フィルタ名 (現在ファイルの種別を初期選択するため)
    _EXT_TO_FILTER = {
        '.txt': "テキストファイル (*.txt)",
        '.log': "ログファイル (*.log)",
        '.sql': "SQLファイル (*.sql)",
        '.py':  "Pythonファイル (*.py)",
        '.js':  "JavaScript (*.js)",
        '.json': "JSON (*.json)",
        '.csv': "CSV (*.csv)",
        '.md':  "Markdown (*.md)",
        '.xml': "XML (*.xml)",
        '.html': "HTML (*.html *.htm)", '.htm': "HTML (*.html *.htm)",
        '.yaml': "YAML (*.yaml *.yml)", '.yml': "YAML (*.yaml *.yml)",
        '.sh':  "シェルスクリプト (*.sh)",
        '.ini': "設定ファイル (*.ini *.conf *.cfg)",
        '.conf': "設定ファイル (*.ini *.conf *.cfg)",
        '.cfg': "設定ファイル (*.ini *.conf *.cfg)",
    }

    def save_file_as(self):
        tab = self.current_tab()
        if not tab:
            return
        # 現在ファイルの拡張子に合うフィルタを初期選択
        ext = os.path.splitext(tab.filename)[1].lower()
        initial_filter = self._EXT_TO_FILTER.get(ext, "テキストファイル (*.txt)")
        path, _ = QFileDialog.getSaveFileName(
            self, "名前を付けて保存", tab.filename,
            self._SAVE_FILTERS,
            initial_filter,
        )
        if path:
            self._write_file(tab, path)

    # 保存可能なエンコーディング (検出時の名称 → Python codec 名)。
    # 'UTF-8 (replace)' のようなフォールバックは UTF-8 として書き戻す。
    _SAVE_ENC_MAP = {
        'utf-8':            'utf-8',
        'utf-8-sig':        'utf-8-sig',     # BOM 付きで書き戻す
        'cp932':            'cp932',
        'shift_jis':        'shift_jis',
        'euc-jp':           'euc-jp',
        'UTF-8 (replace)':  'utf-8',
    }

    def _write_file(self, tab, path):
        # タブが持つ検出済みエンコで書き戻す (UTF-8 強制を撤廃)。
        # encoding に該当 codec が無ければ UTF-8 にフォールバック。
        enc = self._SAVE_ENC_MAP.get(getattr(tab, 'encoding', '') or '', 'utf-8')
        text = tab.editor.toPlainText()
        try:
            # CP932/Shift_JIS 等で表現できない文字を含む場合に備え、
            # errors='strict' で書いてみて、 失敗したらユーザに確認。
            try:
                with open(path, 'w', encoding=enc) as f:
                    f.write(text)
            except UnicodeEncodeError as ue:
                ans = QMessageBox.warning(
                    self, "文字コードで保存できません",
                    f"このファイルは現在 {enc} と判定されていますが、\n"
                    f"内容に {enc} で表現できない文字が含まれています:\n"
                    f"  位置: {ue.start} 付近\n\n"
                    "UTF-8 で保存し直しますか?\n"
                    "(キャンセルで保存を中止)",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Yes,
                )
                if ans != QMessageBox.StandardButton.Yes:
                    return
                enc = 'utf-8'
                with open(path, 'w', encoding=enc) as f:
                    f.write(text)
                tab.encoding = enc
                self._update_encoding_label()
            tab.file_path = path
            tab.filename = os.path.basename(path)
            idx = self.tabs.indexOf(tab)
            self.tabs.setTabText(idx, tab.filename)
            tab.editor.document().setModified(False)
            tab.reset_original()  # 保存後はガターをリセット
            # 保存でパスが付いた/変わったタブのブックマークを永続化
            self._persist_tab_bookmarks(tab)
            self.statusBar().showMessage(
                f"保存しました ({enc}): {path}", 3000)
            # 自分が書いたファイルの fileChanged を 1 秒間無視
            self._self_write_paths.add(path)
            self._self_write_clear_timer.start(1000)
            self._watch_path(path)   # 監視継続 (Qt が一旦解除する場合あり)
        except Exception as e:
            QMessageBox.critical(self, "保存エラー", str(e))

    def _mark_ftp_self_write(self, local_path: str):
        """FTPPanel が DL を開始する直前に呼ばれる。DL 中の chunk 書込みで
        QFileSystemWatcher が発火する fileChanged を _on_external_change に
        無視させるため、 local_path を _self_write_paths に登録する。
        DL 完了後に _open_ftp_file が走るまで継続するよう、 5 秒のタイマで
        クリアする (通常の保存より長め: 大ファイル DL を考慮)。"""
        try:
            self._self_write_paths.add(local_path)
            self._self_write_clear_timer.start(5000)
        except Exception:
            pass

    # ---------------- 外部ファイル変更検知 (VS Code 風) ----------------

    def _watch_path(self, path: str):
        """ファイル変更ウォッチ対象に追加"""
        if path and os.path.isfile(path):
            if path not in self._fs_watcher.files():
                self._fs_watcher.addPath(path)

    def _unwatch_path(self, path: str):
        if path and path in self._fs_watcher.files():
            self._fs_watcher.removePath(path)

    def _on_external_change(self, path: str):
        """ファイルが外部で書き換えられた時の処理"""
        # 自分が書き込んだ直後のイベントは無視
        if path in self._self_write_paths:
            return
        # 削除されている場合はスキップ (再作成されればまた発火する)
        if not os.path.isfile(path):
            # Qt は削除でも watch を解除するので再追加は不要
            self.statusBar().showMessage(
                f"ファイルが削除されました: {os.path.basename(path)}", 5000
            )
            return

        # 該当タブを探す (複数あれば全部更新)
        for i in range(self.tabs.count()):
            tab = self.tabs.widget(i)
            if not isinstance(tab, EditorTab) or tab.file_path != path:
                continue
            try:
                new_content = self._read_text_auto_encoding(path)
            except Exception:
                continue
            if new_content == tab.editor.toPlainText():
                continue   # 実質変化なし

            if tab.editor.document().isModified():
                # 未保存編集あり: 確認
                ans = QMessageBox.question(
                    self, "外部で変更されました",
                    f"{os.path.basename(path)} は外部で変更されました。\n"
                    "このタブには未保存の編集があります。\n\n"
                    "リロードすると未保存編集は失われます。\n"
                    "リロードしますか？",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if ans == QMessageBox.StandardButton.Yes:
                    self._reload_tab_content(tab, new_content)
            else:
                # 未編集 → 自動リロード
                self._reload_tab_content(tab, new_content)
                self.statusBar().showMessage(
                    f"{os.path.basename(path)} が外部で変更されたためリロードしました",
                    4000,
                )

        # Qt FSWatcher は変更1回で監視解除されることがあるので再登録
        self._watch_path(path)

    def _reload_tab_content(self, tab, new_content: str):
        """タブの内容を新コンテンツに置き換え (カーソル位置をなるべく保持)。
        ● マーク誤検知防止のため reload_from_disk を経由する。"""
        cur_block = tab.editor.textCursor().blockNumber()
        tab.reload_from_disk(new_content)
        try:
            tab.highlighter.rehighlight()
        except Exception:
            pass
        self._jump_to_line(tab.editor, cur_block + 1)

    def save_all(self) -> bool:
        """全タブを保存。パス未指定のタブは「名前を付けて保存」プロンプト。
        戻り値: 全て保存に成功したら True、ユーザーがキャンセルしたら False"""
        saved = 0
        skipped = 0
        for i in range(self.tabs.count()):
            tab = self.tabs.widget(i)
            if not isinstance(tab, EditorTab):
                continue
            if not tab.editor.document().isModified():
                continue
            if tab.file_path:
                # 直接保存
                self._write_file(tab, tab.file_path)
                saved += 1
            else:
                # ファイル名未定 → ダイアログ表示用にタブを切り替えてSave As
                self.tabs.setCurrentIndex(i)
                path, _ = QFileDialog.getSaveFileName(
                    self, f"保存: {tab.filename}", tab.filename,
                    "すべてのファイル (*);;"
                    "Pythonファイル (*.py);;"
                    "テキストファイル (*.txt)",
                )
                if path:
                    self._write_file(tab, path)
                    saved += 1
                else:
                    skipped += 1   # ユーザーがキャンセル
        if saved:
            self.statusBar().showMessage(
                f"全タブ保存完了: {saved} 件" + (f" / スキップ {skipped} 件" if skipped else ""),
                3000,
            )
        elif skipped == 0:
            self.statusBar().showMessage("変更されたタブはありません", 2000)
        return skipped == 0

    def save_all_and_exit(self):
        """全タブを保存 → アプリ終了。未保存があってキャンセルされたら終了しない。"""
        if self.save_all():
            self.close()

    @staticmethod
    def _tab_actually_modified(tab) -> bool:
        """EditorTab の is_modified フラグだけでは syntax highlighter の format
        変更等で誤検知される事があるため、現テキスト vs _original_lines を
        実比較して True/False を返す。

        '\\n'.join() と toPlainText() は末尾改行の扱いが微妙に違うため、
        両方を splitlines() で行単位に正規化して比較する (改行差異を吸収)。"""
        try:
            current_lines = tab.editor.toPlainText().splitlines()
            original_lines = getattr(tab, '_original_lines', [])
            return current_lines != original_lines
        except Exception:
            return True  # 比較失敗時は安全側 (修正されている扱い)

    def _close_tab(self, idx):
        tab = self.tabs.widget(idx)
        if isinstance(tab, EditorTab) and tab.is_modified and self._tab_actually_modified(tab):
            ans = QMessageBox.question(
                self, "確認",
                f"「{tab.filename}」は変更されています。保存しますか？",
                QMessageBox.StandardButton.Save |
                QMessageBox.StandardButton.Discard |
                QMessageBox.StandardButton.Cancel,
            )
            if ans == QMessageBox.StandardButton.Save:
                self.tabs.setCurrentIndex(idx)
                self.save_file()
            elif ans == QMessageBox.StandardButton.Cancel:
                return
        # ファイル監視を解除 (他タブで同じファイルを開いていれば残す)
        if isinstance(tab, EditorTab) and tab.file_path:
            still_used = any(
                isinstance(self.tabs.widget(i), EditorTab) and
                self.tabs.widget(i).file_path == tab.file_path and
                self.tabs.widget(i) is not tab
                for i in range(self.tabs.count())
            )
            if not still_used:
                self._unwatch_path(tab.file_path)
        self.tabs.removeTab(idx)
        if self.tabs.count() == 0:
            self.new_file()

    # --- その他のスロット ---

    def _show_search(self, show_replace: bool = False):
        tab = self.current_tab()
        if not tab:
            return
        # Grep パネルとの同時表示を避けて状態の混乱を防ぐ
        self._hide_grep_panel()
        # 選択中なら自動入力 (改行を含む選択は最初の行だけ)
        sel = tab.editor.textCursor().selectedText()
        # Qt の selectedText は改行を U+2029 で返す
        for sep in (' ', ' ', '\n', '\r'):
            if sep in sel:
                sel = sel.split(sep)[0]
                break
        tab.search_bar.show_bar(
            initial_text=sel if sel else None,
            show_replace=show_replace,
        )
        self._sync_toolbar_states()

    def _show_replace(self):
        """検索・置換 (Ctrl+H) — 検索バーを置換欄も含めて開く。"""
        self._show_search(show_replace=True)

    def _search_selection_next(self):
        """選択語を即検索して次の一致へジャンプ (バーを開かず素早く)"""
        tab = self.current_tab()
        if not tab:
            return
        sel = tab.editor.textCursor().selectedText()
        for sep in (' ', ' ', '\n', '\r'):
            if sep in sel:
                sel = sel.split(sep)[0]
                break
        if not sel:
            return
        # 検索バーに入れてハイライトもさせる
        tab.search_bar.show_bar(initial_text=sel)
        tab.search_bar.find_next()

    def _show_grep(self):
        # 通常検索 (InlineSearchBar) との同時表示を避けて状態の混乱を防ぐ
        self._hide_inline_search()
        self.grep_panel.show()
        self.bottom_splitter.show()
        tab = self.current_tab()
        if tab and tab.file_path:
            self.grep_panel.set_directory(os.path.dirname(tab.file_path))
        self.grep_panel.pattern_input.setFocus()
        self._ensure_bottom_height()
        self._sync_toolbar_states()

    def _hide_grep_panel(self):
        """Grep パネル (下部) を隠す。"""
        try:
            self.grep_panel.hide()
            self.bottom_splitter.hide()
        except Exception:
            pass
        self._sync_toolbar_states()

    def _hide_bookmark_panel(self):
        """ブックマークパネル (右サイドバー) を隠す。"""
        try:
            self.bookmark_panel.hide()
        except Exception:
            pass
        self._sync_toolbar_states()

    # --- ツールバートグル ---

    def _toggle_grep_panel(self):
        if self.grep_panel.isVisible():
            self._hide_grep_panel()
        else:
            self._show_grep()
        self._sync_toolbar_states()

    def _toggle_bookmark_panel(self):
        if self.bookmark_panel.isVisible():
            self._hide_bookmark_panel()
        else:
            self._show_bookmarks()
        self._sync_toolbar_states()

    def _toggle_search_bar(self):
        tab = self.current_tab()
        if not tab or not hasattr(tab, 'search_bar'):
            return
        if tab.search_bar.isVisible():
            tab.search_bar.close_bar()
        else:
            self._show_search()
        self._sync_toolbar_states()

    def _sync_toolbar_states(self):
        """ツールバーのトグルチェック状態を実際の表示状態と同期する。"""
        if hasattr(self, '_grep_toolbar_action'):
            self._grep_toolbar_action.blockSignals(True)
            self._grep_toolbar_action.setChecked(self.grep_panel.isVisible())
            self._grep_toolbar_action.blockSignals(False)
        if hasattr(self, '_bookmark_toolbar_action'):
            self._bookmark_toolbar_action.blockSignals(True)
            self._bookmark_toolbar_action.setChecked(self.bookmark_panel.isVisible())
            self._bookmark_toolbar_action.blockSignals(False)
        if hasattr(self, '_search_toolbar_action'):
            tab = self.current_tab()
            search_visible = bool(
                tab and hasattr(tab, 'search_bar') and tab.search_bar.isVisible()
            )
            self._search_toolbar_action.blockSignals(True)
            self._search_toolbar_action.setChecked(search_visible)
            self._search_toolbar_action.blockSignals(False)

    def _hide_inline_search(self):
        """全タブのインライン検索バーを閉じる。"""
        for i in range(self.tabs.count()):
            tab = self.tabs.widget(i)
            if hasattr(tab, 'search_bar') and tab.search_bar.isVisible():
                try:
                    tab.search_bar.hide()
                    # 検索ハイライトもクリア
                    if hasattr(tab.editor, 'set_search_highlights'):
                        tab.editor.set_search_highlights([])
                except Exception:
                    pass
        self._sync_toolbar_states()

    # --- ブックマーク操作 ---

    def _toggle_bookmark(self):
        editor = self.current_editor()
        if editor:
            editor.toggle_bookmark()

    def _next_bookmark(self):
        editor = self.current_editor()
        if editor:
            editor.goto_next_bookmark(forward=True)

    def _next_change(self):
        editor = self.current_editor()
        if editor:
            if not editor._change_map:
                self.statusBar().showMessage("変更箇所はありません", 2000)
                return
            editor.goto_next_change(forward=True)

    def _prev_change(self):
        editor = self.current_editor()
        if editor:
            if not editor._change_map:
                self.statusBar().showMessage("変更箇所はありません", 2000)
                return
            editor.goto_next_change(forward=False)

    def _prev_bookmark(self):
        editor = self.current_editor()
        if editor:
            editor.goto_next_bookmark(forward=False)

    def _next_error(self):
        editor = self.current_editor()
        if editor:
            editor.goto_next_error(forward=True)

    def _prev_error(self):
        editor = self.current_editor()
        if editor:
            editor.goto_next_error(forward=False)

    def _show_bookmarks(self):
        self.bookmark_panel.show()
        self._refresh_bookmarks()
        self._ensure_bookmark_width()
        self._sync_toolbar_states()

    def _ensure_bookmark_width(self, target: int = 320):
        """右サイドバーのブックマークパネルに初期幅を確保する (狭すぎ/0 を防ぐ)。"""
        def _apply():
            total = self.splitter.width()
            sizes = self.splitter.sizes()
            if total <= 0 or len(sizes) < 3:
                return
            if sizes[2] >= target:
                return
            ftp_w = sizes[0]
            give = min(target, max(total // 3, 240))
            center = max(total - ftp_w - give, 320)
            self.splitter.setSizes([ftp_w, center, give])
        QTimer.singleShot(0, _apply)

    def _ensure_bottom_height(self, min_bottom: int = 300):
        """下部パネル (Grep/ブックマーク) 表示時に高さが足りなければ広げる。
        行が見切れないよう、下部に最低でも min_bottom px 程度を確保する。
        """
        def _apply():
            total = self.v_splitter.height()
            if total <= 0:
                return
            sizes = self.v_splitter.sizes()
            if len(sizes) < 2:
                return
            # 下部の目標高さ (画面が小さい時は半分まで)
            target = min(min_bottom, max(total // 2, 200))
            if sizes[1] < target:
                top = max(total - target, 150)
                self.v_splitter.setSizes([top, target])
        # レイアウト確定後にサイズ取得・適用 (初回表示直後は height が未確定なため)
        QTimer.singleShot(0, _apply)

    def _show_sql_extract(self, *, selection_only: bool = False):
        """SQL抽出ダイアログを開く。
        selection_only=True の時は、エディタの選択範囲だけを対象に抽出する
        (ログを参照中に「この辺の SQL だけ抜き出したい」ユースケース)。
        """
        tab = self.current_tab()
        if not tab:
            QMessageBox.information(self, "情報", "ファイルを開いてください。")
            return

        title = tab.filename
        if selection_only:
            cur = tab.editor.textCursor()
            sel_text = cur.selection().toPlainText()
            if not sel_text.strip():
                QMessageBox.information(
                    self, "選択範囲なし",
                    "エディタでログ範囲を選択してから実行してください。\n"
                    "(複数行を選択して右クリック → 「選択範囲からSQL抽出」)"
                )
                return
            content = sel_text
            # 選択範囲の開始行をタイトルに表示してコンテキスト分かりやすく
            start_line = tab.editor.document().findBlock(cur.selectionStart()).blockNumber() + 1
            end_line = tab.editor.document().findBlock(cur.selectionEnd()).blockNumber() + 1
            title = f"{tab.filename} (選択 行{start_line}-{end_line})"
        else:
            content = tab.editor.toPlainText()
            if not content.strip():
                QMessageBox.information(self, "情報", "ファイルが空です。")
                return

        # モードレス表示 — メイン画面の編集や別タブの操作と並行して使える
        dlg = SqlExtractDialog(content, title, parent=self)
        dlg.setWindowModality(Qt.WindowModality.NonModal)
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dlg.open_sql_requested.connect(self._open_sql_content)
        # ガベージコレクション対策で参照を保持 (閉じたら自動で除外)
        if not hasattr(self, '_open_dialogs'):
            self._open_dialogs: list = []
        self._open_dialogs.append(dlg)
        dlg.destroyed.connect(
            lambda _=None, d=dlg: self._open_dialogs.remove(d)
            if d in self._open_dialogs else None
        )
        dlg.show()

    def _show_sql_extract_selection(self):
        """エディタの選択範囲からSQLを抽出 → ダイアログ表示。"""
        self._show_sql_extract(selection_only=True)

    def _open_source_from_selection(self):
        """選択範囲 (無ければ現在行) のソース参照を解析し、登録ソース検索パスから開く。
        Class#method():行 / スタックトレース / File.ext:行 を抽出し、
        登録済みソース検索パスを再帰検索して該当ファイルの該当行へジャンプする。
        """
        tab = self.current_tab()
        if not tab:
            return
        cursor = tab.editor.textCursor()
        text = cursor.selectedText() if cursor.hasSelection() else ''
        # QPlainTextEdit の selectedText は段落区切りが U+2028 になるので復元
        text = text.replace(' ', '\n').replace(' ', '\n')
        if not text.strip():
            text = cursor.block().text()   # 選択が無ければ現在行

        refs = _extract_source_refs(text)
        if not refs:
            QMessageBox.information(
                self, "ソース参照なし",
                "選択範囲 (または現在行) からソース参照を検出できませんでした。\n"
                "例: WP50121Servlet#createValueList():995 / (Foo.java:123) / utils.py:42")
            return

        source_dirs = SETTINGS.get('source_dirs') or []
        if not source_dirs:
            ans = QMessageBox.question(
                self, "ソース検索パス未登録",
                "ソースの検索先 (ソース検索パス) が未登録です。\n"
                "今すぐ設定で登録しますか？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if ans == QMessageBox.StandardButton.Yes:
                self._open_settings()
            return

        # 各参照について候補ファイルを解決 (ref 全体を保持してメソッド検索に使う)
        entries = []
        total_candidates = 0
        for r in refs:
            paths = _resolve_source_file(r, source_dirs)
            total_candidates += len(paths)
            entries.append({'ref': r, 'paths': paths})

        if total_candidates == 0:
            names = ', '.join(
                (r['filename'] or (r['classname'] + '.*')) for r in refs)
            QMessageBox.warning(
                self, "ソースが見つかりません",
                f"登録済みソース検索パスから該当ファイルが見つかりませんでした:\n{names}\n\n"
                "設定でソース検索パスが正しいか確認してください。")
            return

        # 候補が1件だけなら直接開く。複数なら選択ダイアログ。
        single = [(e['paths'][0], e['ref']) for e in entries if len(e['paths']) == 1]
        if total_candidates == 1 and len(single) == 1:
            path, ref = single[0]
            self._open_source_target(path, ref)
            return

        dlg = SourceRefPickerDialog(entries, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            targets = dlg.results()
            for path, ref in targets:
                self._open_source_target(path, ref)
            if len(targets) > 1:
                self.statusBar().showMessage(
                    f"ソースを {len(targets)} 件開きました", 4000)

    def _open_source_target(self, path: str, ref: dict):
        """解決済みパスを開き、行番号があればその行へ、無ければメソッド定義へジャンプ。
        ジャンプ先の行には自動でブックマークを付ける (調査箇所を後から辿れるように)。
        """
        line = int(ref.get('line') or 0)
        if line > 0:
            self._open_file_at_line(path, line, '')
            self._auto_bookmark(line)
            self.statusBar().showMessage(f"ソースを開きました: {path}:{line}", 4000)
            return
        # 行番号が無い (C++ 等) → ファイルを開いてメソッド定義を検索しジャンプ
        self._open_file_at_line(path, 1, '')
        method = ref.get('method', '')
        classname = ref.get('classname', '')
        tab = self.current_tab()
        if not tab or not method:
            self.statusBar().showMessage(f"ソースを開きました: {path}", 4000)
            return
        doc = tab.editor.document()
        pat_def = re.compile(r'\b' + re.escape(classname) + r'\s*::\s*'
                             + re.escape(method) + r'\b') if classname else None
        pat_call = re.compile(r'\b' + re.escape(method) + r'\s*\(')
        best = None
        for i in range(doc.blockCount()):
            t = doc.findBlockByNumber(i).text()
            if pat_def and pat_def.search(t):
                best = i
                break
            if best is None and pat_call.search(t):
                best = i
        if best is not None:
            self._jump_to_line(tab.editor, best + 1)
            self._auto_bookmark(best + 1)
            self.statusBar().showMessage(
                f"ソースを開きました: {path} ({method} を検索)", 4000)
        else:
            self.statusBar().showMessage(
                f"ソースを開きました: {path} (メソッド {method} は未検出)", 4000)

    def _auto_bookmark(self, lineno: int):
        """現在のタブのエディタの指定行に自動でブックマークを付ける。"""
        tab = self.current_tab()
        if tab and lineno > 0:
            tab.editor.add_bookmark(lineno)
            # シグナル経由に依存せず確実に永続化する
            self._persist_tab_bookmarks(tab)

    def _open_sql_content(self, content: str, filename: str):
        tab = EditorTab(content, filename)
        self._connect_tab(tab)
        idx = self.tabs.addTab(tab, filename)
        self.tabs.setCurrentIndex(idx)

    def apply_open_request(self, req: dict):
        """起動引数 / 別プロセスからの IPC 要求を共通処理する。
        - files: 開くファイル (既に開いていればそのタブをアクティブ化)
        - profile: DB実行の初期プロファイル
        - search: 起動後に検索バーで自動検索
        - sql_extract: SQL抽出ダイアログを自動で開く
        """
        files = req.get('files') or []
        profile = req.get('profile') or ''
        search = req.get('search') or ''
        sql_extract = bool(req.get('sql_extract'))

        if profile:
            self._origin_profile = profile

        opened_any = False
        for f in files:
            if not os.path.isfile(f):
                continue
            # 既に開いていれば再ロードせずそのタブをアクティブ化
            target = os.path.normcase(os.path.normpath(os.path.abspath(f)))
            found = False
            for idx in range(self.tabs.count()):
                t = self.tabs.widget(idx)
                if isinstance(t, EditorTab) and t.file_path:
                    cur = os.path.normcase(os.path.normpath(os.path.abspath(t.file_path)))
                    if cur == target:
                        self.tabs.setCurrentIndex(idx)
                        found = True
                        break
            if not found:
                self._load_file(f)
            opened_any = True

        if search:
            tab = self.current_tab()
            if tab and hasattr(tab, 'search_bar'):
                tab.search_bar.show_bar(initial_text=search)
                # --regex 指定時は検索バーの正規表現トグルを ON
                # (toggle 後に _update_highlights が自動再実行され、
                #  regex モードで正しくハイライトされる)
                if req.get('regex') and hasattr(tab.search_bar, 'regex_check'):
                    tab.search_bar.regex_check.setChecked(True)
                # 最初のマッチに自動ジャンプ (条件入りだけでカーソルが動かないと
                # 「検索条件は入っているのにマッチが見えない」状態になるため)
                QTimer.singleShot(0, tab.search_bar.find_next)

        if sql_extract and opened_any:
            QTimer.singleShot(0, self._show_sql_extract)

        # ウィンドウを前面に出す (最小化されていても復帰)
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _refresh_bookmarks(self):
        refs = []
        for i in range(self.tabs.count()):
            tab = self.tabs.widget(i)
            if isinstance(tab, EditorTab):
                refs.append((self.tabs.tabText(i).lstrip('● '), tab))
        self.bookmark_panel.set_tabs(refs)

    def _jump_to_bookmark(self, tab, lineno):
        idx = self.tabs.indexOf(tab)
        if idx >= 0:
            self.tabs.setCurrentIndex(idx)
        self._jump_to_line(tab.editor, lineno)

    def _open_file_at_line(self, filepath, lineno, line_text: str = ''):
        # パスの差異 (相対/絶対, 区切り文字) を吸収して既存タブを検索
        try:
            target = os.path.normcase(os.path.normpath(os.path.abspath(filepath)))
        except Exception:
            target = filepath
        for i in range(self.tabs.count()):
            tab = self.tabs.widget(i)
            if not isinstance(tab, EditorTab) or not tab.file_path:
                continue
            try:
                cur_path = os.path.normcase(os.path.normpath(os.path.abspath(tab.file_path)))
            except Exception:
                cur_path = tab.file_path
            if cur_path == target:
                self.tabs.setCurrentIndex(i)
                # grep は最新のディスク内容に対して行番号を返すので、
                # タブ内エディタの内容が古い (ログが追記された等) ままだと
                # 行番号がズレる。ジャンプ前にディスクと内容を比較して
                # 必要ならリロードする。
                self._reload_if_stale(tab, filepath)
                self._jump_to_line_smart(tab.editor, lineno, line_text)
                return
        # 新しく開く
        self._load_file(filepath)
        tab = self.current_tab()
        if tab:
            self._jump_to_line_smart(tab.editor, lineno, line_text)

    def _jump_to_line_smart(self, editor, lineno: int, line_text: str = ''):
        """行番号 + 行テキストの両方を使ってロバストにジャンプ。
        - line_text が空: 通常の行番号ジャンプ
        - line_text あり: 行番号の位置を起点に、近傍 → 全文 の順でテキスト検索
          一致した行にジャンプ。これでログ追記でズレた行番号でも正しい行に行ける。
        """
        if not line_text:
            self._jump_to_line(editor, lineno)
            return
        doc = editor.document()
        if doc is None:
            return
        total = doc.blockCount()
        # まず行番号位置の内容を見て、一致していればそのまま使う
        target_idx = max(0, min(lineno - 1, total - 1))
        target_text = line_text.rstrip()

        def _line_at(idx: int) -> str:
            b = doc.findBlockByNumber(idx)
            return b.text() if b.isValid() else ''

        # 1. 行番号位置で正確一致
        if _line_at(target_idx).rstrip() == target_text:
            self._jump_to_line(editor, target_idx + 1)
            return

        # 2. 近傍 ±200 行で探索 (ログの追記で多少ズレた程度を想定)
        WINDOW = 200
        lo = max(0, target_idx - WINDOW)
        hi = min(total, target_idx + WINDOW + 1)
        for idx in range(lo, hi):
            if _line_at(idx).rstrip() == target_text:
                self._jump_to_line(editor, idx + 1)
                self.statusBar().showMessage(
                    f"行番号がズレていたためテキスト一致でジャンプ: "
                    f"{lineno} → {idx + 1}", 4000,
                )
                return

        # 3. 全文を 1 回スキャン (大規模ファイルでも数千行/数十万行は OK)
        for idx in range(total):
            if _line_at(idx).rstrip() == target_text:
                self._jump_to_line(editor, idx + 1)
                self.statusBar().showMessage(
                    f"全文一致でジャンプ: {lineno} → {idx + 1}", 4000,
                )
                return

        # 4. 完全一致が無い → 部分一致でフォールバック
        needle = target_text.strip()
        if needle:
            for idx in range(total):
                if needle in _line_at(idx):
                    self._jump_to_line(editor, idx + 1)
                    self.statusBar().showMessage(
                        f"部分一致でジャンプ: {lineno} → {idx + 1}", 4000,
                    )
                    return

        # 5. それでも見つからなければ行番号通りジャンプ (行数オーバーでも clamp 済)
        self._jump_to_line(editor, lineno)
        self.statusBar().showMessage(
            "マッチ行が見つかりませんでした (ファイル内容が大きく変わった可能性)",
            4000,
        )

    def _reload_if_stale(self, tab, filepath: str):
        """ディスクのファイル内容とタブの内容が異なる時、未保存編集が無ければ自動リロード。
        grep / 外部ジャンプ時にエディタの行番号とディスクの行番号を一致させるためのヘルパー。
        """
        try:
            if tab.editor.document().isModified():
                # 未保存編集ありの場合は触らない (ユーザー編集を失わない)
                return
            disk_content = self._read_text_auto_encoding(filepath)
        except Exception:
            return
        cur_content = tab.editor.toPlainText()
        if disk_content == cur_content:
            return
        # 内容が変わっている → リロード
        # 自己書き込み起因の watcher 誤検知を避けるため、書き込み追跡セットには触らない
        tab.editor.setPlainText(disk_content)
        try:
            tab._original_lines = disk_content.splitlines()
        except Exception:
            pass
        tab.editor.document().setModified(False)
        try:
            tab.highlighter.rehighlight()
        except Exception:
            pass
        self.statusBar().showMessage(
            f"{os.path.basename(filepath)} を最新内容にリロードしました (grep結果の行番号と一致)",
            4000,
        )

    def _jump_to_line(self, editor, lineno):
        """指定行 (1-based) にカーソルを移してビューを中央スクロール。
        - 検索バーやGrepパネルから呼ばれた直後はフォーカスや描画タイミングが
          噛み合わないことがあるため、即時 + QTimer.singleShot(0) の二段階で
          確実に反映させる。
        """
        def _do_jump():
            doc = editor.document()
            if doc is None:
                return
            total = doc.blockCount()
            ln = max(1, min(lineno, total))
            block = doc.findBlockByNumber(ln - 1)
            if not block.isValid():
                return
            cursor = editor.textCursor()
            cursor.clearSelection()
            cursor.setPosition(block.position())
            editor.setTextCursor(cursor)
            editor.setFocus(Qt.FocusReason.OtherFocusReason)
            editor.ensureCursorVisible()
            editor.centerCursor()
        _do_jump()
        # 直後の各種シグナル処理 (highlight_current_line 等) が走った後に
        # もう一度センタリングしてズレを防ぐ
        QTimer.singleShot(0, _do_jump)

    def _show_goto_line(self):
        """ダイアログで行番号を入力して指定行にジャンプ"""
        editor = self.current_editor()
        if not editor:
            return
        total = editor.document().blockCount()
        cur = editor.textCursor().blockNumber() + 1
        line, ok = QInputDialog.getInt(
            self, "行へジャンプ",
            f"行番号を入力 (1〜{total}):",
            value=cur, min=1, max=max(1, total),
        )
        if ok:
            self._jump_to_line(editor, line)

    def _toggle_ftp(self):
        if self.ftp_panel.isVisible():
            self.ftp_panel.hide()
        else:
            self.ftp_panel.show()
            self._ensure_ftp_width()
        # ツールバー + メニュー両方のチェック状態を実状態に同期 (片方だけだと
        # ツールバーアイコンで開いた後にメニューを開くとチェックが外れていて
        # 操作がズレる)
        visible = self.ftp_panel.isVisible()
        for attr in ('_ftp_toolbar_action', '_ftp_menu_action'):
            a = getattr(self, attr, None)
            if a is not None:
                a.blockSignals(True)
                a.setChecked(visible)
                a.blockSignals(False)

    def _ensure_ftp_width(self, target: int = 260):
        """左サイドバー(FTP)表示時に幅を確保する。
        ブックマーク表示で splitter サイズが確定し FTP が 0 幅になっていても、
        開いた時にきちんと表示されるようにする。
        """
        def _apply():
            total = self.splitter.width()
            sizes = self.splitter.sizes()      # [ftp, center, bookmark]
            if total <= 0 or len(sizes) < 3:
                return
            if sizes[0] >= self.ftp_panel.minimumWidth():
                return   # 既に十分な幅がある
            bm = sizes[2]                       # ブックマーク幅 (非表示なら 0)
            give = min(target, self.ftp_panel.maximumWidth())
            center = max(total - give - bm, 320)
            self.splitter.setSizes([give, center, bm])
        QTimer.singleShot(0, _apply)

    def _on_content_changed(self):
        tab = self.current_tab()
        if not tab:
            return
        idx = self.tabs.indexOf(tab)
        title = tab.filename
        bar = self.tabs.tabBar()
        if tab.is_modified:
            # 未保存マーク ● + タブ文字色をオレンジにして目立たせる
            title = f"● {title}"
            bar.setTabTextColor(idx, QColor("#FFB454"))
        else:
            # 保存済み → デフォルト色に戻す (QColor() = 無効色 = テーマ既定)
            bar.setTabTextColor(idx, QColor())
        self.tabs.setTabText(idx, title)

    def _on_tab_changed(self, _):
        self._update_cursor()
        self._sync_language_combo()
        self._update_encoding_label()
        # 検索バーは各タブが個別に持つので、タブ切替時にトグル状態を同期
        if hasattr(self, '_sync_toolbar_states'):
            self._sync_toolbar_states()

    def _sync_csv_view_action(self):
        """表示メニュー展開時、 現在のタブの種類に応じて切替アクションのラベルと
        有効/無効を設定する。 ついでに FTPパネル の checked 状態も同期。"""
        # FTP メニューチェックを実状態に同期 (ツールバーアイコンで開閉した時の
        # 状態ズレ防止)
        if hasattr(self, '_ftp_menu_action') and hasattr(self, 'ftp_panel'):
            self._ftp_menu_action.blockSignals(True)
            self._ftp_menu_action.setChecked(self.ftp_panel.isVisible())
            self._ftp_menu_action.blockSignals(False)
        if not hasattr(self, '_toggle_csv_view_action'):
            return
        w = self.tabs.currentWidget()
        if isinstance(w, CsvTab):
            self._toggle_csv_view_action.setText("📝 テキスト編集に切替(&G)")
            self._toggle_csv_view_action.setEnabled(True)
        elif isinstance(w, EditorTab) and w.file_path and _is_csv_path(w.file_path):
            self._toggle_csv_view_action.setText("📊 CSV グリッド表示に切替(&G)")
            self._toggle_csv_view_action.setEnabled(True)
        else:
            self._toggle_csv_view_action.setText("📊 CSV グリッド表示に切替(&G)")
            self._toggle_csv_view_action.setEnabled(False)

    def _toggle_csv_view(self):
        """現在のタブが CSV ファイルなら EditorTab ⇄ CsvTab を切替える。
        編集中の未保存テキストはメモリ上で受け渡し (ディスクには書き込まない)。
        """
        w = self.tabs.currentWidget()
        if isinstance(w, CsvTab):
            # グリッド → テキスト編集 (既存の経路を再利用)
            self._reopen_csv_as_text(w, w.file_path or '')
            return
        if isinstance(w, EditorTab) and w.file_path and _is_csv_path(w.file_path):
            # エディタ → グリッド: 現在のテキスト内容で CsvTab を生成
            current_text = w.editor.toPlainText()
            enc = getattr(w, 'encoding', '') or 'utf-8'
            path = w.file_path
            filename = w.filename or os.path.basename(path)
            # 既存の EditorTab を閉じる前に未保存編集があれば確認
            if w.is_modified and self._tab_actually_modified(w):
                ans = QMessageBox.question(
                    self, "未保存の変更",
                    "未保存の編集があります。\n"
                    "グリッドに切替えると編集はファイルに保存されないまま\n"
                    "メモリ上でグリッド表示にだけ反映されます。\n"
                    "切替えますか？ (キャンセルで EditorTab に留まる)",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes,
                )
                if ans != QMessageBox.StandardButton.Yes:
                    return
            idx = self.tabs.indexOf(w)
            if idx >= 0:
                self.tabs.removeTab(idx)
                w.deleteLater()
            tab = CsvTab(path, filename, current_text, enc)
            tab.open_as_text_requested.connect(
                lambda p, _t=tab: self._reopen_csv_as_text(_t, p))
            new_idx = self.tabs.addTab(tab, f"📊 {filename}")
            self.tabs.setCurrentIndex(new_idx)
            self._update_encoding_label()

    def _reopen_csv_as_text(self, csv_tab, path: str):
        """CsvTab → EditorTab に切替。 CsvTab の _raw_text を使うので、
        グリッド → エディタ → グリッドの往復で内容が保たれる
        (= EditorTab で編集 → グリッドへ戻る → エディタへ戻るで編集消失しない)。
        ディスクに存在するファイルなら現テキスト vs ディスクを比較して、
        差分があれば ● マークも復活させる (toggle 時に編集状態が消える問題対策)。
        ファイルがディスクに存在しない (= 新規 CsvTab) ケースもサポート。"""
        try:
            # CsvTab 内のテキスト (= 表示中の内容) をそのまま EditorTab へ渡す
            content = getattr(csv_tab, '_raw_text', '') or ''
            enc = getattr(csv_tab, 'encoding', '') or 'utf-8'
            filename = getattr(csv_tab, 'filename', '') or (
                os.path.basename(path) if path else '無題.csv')
            # 既存 CsvTab を閉じる
            for i in range(self.tabs.count()):
                if self.tabs.widget(i) is csv_tab:
                    self.tabs.removeTab(i)
                    csv_tab.deleteLater()
                    break
            # 大ファイル抑制は _raw_text 長で代用
            size = len(content.encode('utf-8', errors='replace'))
            skip_hl = size >= self._LARGE_FILE_SIZE
            huge    = size >= self._HUGE_FILE_SIZE
            tab = EditorTab(
                content, filename, path if path else None,
                skip_initial_highlight=skip_hl,
                disable_diff=huge,
                disable_undo=huge,
            )
            tab.encoding = enc
            self._connect_tab(tab)
            idx = self.tabs.addTab(tab, filename)
            self.tabs.setCurrentIndex(idx)
            tab.editor.document().setModified(False)
            # ディスクと比較して ● を再判定する。 ディスク上のテキストを
            # _original_lines にして、 現テキストとの差分があれば編集扱い。
            # この処理が無いとグリッド ⇄ エディタ往復で ● が消える。
            if path and os.path.isfile(path):
                try:
                    disk_text = self._read_text_auto_encoding(path)
                except Exception:
                    disk_text = content
                disk_lines = disk_text.splitlines()
                tab._original_lines = disk_lines
                cur_lines = content.splitlines()
                if cur_lines != disk_lines:
                    # 編集扱いに復元 (● を出す)
                    tab._user_edited = True
                    tab.is_modified = True
                    tab.editor.document().setModified(True)
                    tab.content_changed.emit()
            if path:
                self._restore_tab_bookmarks(tab)
                self._watch_path(path)
            self._update_encoding_label()
        except Exception as e:
            QMessageBox.critical(self, "エラー",
                                 f"テキストとして開けませんでした:\n{e}")

    def _update_encoding_label(self):
        """現在のタブの検出エンコーディングをステータスバーに反映。
        未確定 / 画像タブ / 無題タブは '—' を表示。"""
        if not hasattr(self, 'enc_label'):
            return
        tab = self.current_tab()
        enc = getattr(tab, 'encoding', '') if tab else ''
        # 表示は短く: utf-8-sig → UTF-8 BOM, utf-8 → UTF-8, cp932 → CP932
        labels = {
            'utf-8':     'UTF-8',
            'utf-8-sig': 'UTF-8 BOM',
            'cp932':     'CP932',
            'shift_jis': 'Shift_JIS',
            'euc-jp':    'EUC-JP',
        }
        text = labels.get(enc, enc) if enc else '—'
        self.enc_label.setText(f"文字: {text}")

    def _sync_language_combo(self):
        """現在のタブの言語をステータスバーのコンボに反映 (シグナル抑止)"""
        tab = self.current_tab()
        if not tab:
            return
        lang = getattr(tab.highlighter, 'language', 'text')
        self.lang_combo.blockSignals(True)
        i = self.lang_combo.findText(lang)
        if i >= 0:
            self.lang_combo.setCurrentIndex(i)
        self.lang_combo.blockSignals(False)

    def _on_language_changed(self, lang: str):
        """ユーザーがコンボで言語を切り替えたとき"""
        tab = self.current_tab()
        if tab and hasattr(tab, 'highlighter'):
            tab.highlighter.set_language(lang)

    def _update_cursor(self):
        editor = self.current_editor()
        if editor:
            c = editor.textCursor()
            self.pos_label.setText(f"行: {c.blockNumber()+1}  列: {c.columnNumber()+1}")

    def closeEvent(self, event):
        # 終了前に全タブのブックマークを念のため永続化
        try:
            self._persist_all_bookmarks()
        except Exception:
            pass

        # 未保存タブの確認 — Yes/No ではなく明示的に「終了」「キャンセル」
        for i in range(self.tabs.count()):
            tab = self.tabs.widget(i)
            if isinstance(tab, EditorTab) and tab.is_modified:
                # is_modified が True でも、実際の内容が _original_lines と
                # 一致するならハイライタの format 変更等による誤検知。
                # 内容比較で false positive を弾く。
                if self._tab_actually_modified(tab):
                    msg = QMessageBox(self)
                    msg.setIcon(QMessageBox.Icon.Question)
                    msg.setWindowTitle("終了確認")
                    msg.setText("保存されていない変更があります。終了しますか？")
                    btn_quit   = msg.addButton("終了", QMessageBox.ButtonRole.AcceptRole)
                    btn_cancel = msg.addButton("キャンセル", QMessageBox.ButtonRole.RejectRole)
                    msg.setDefaultButton(btn_cancel)
                    msg.exec()
                    if msg.clickedButton() is btn_cancel:
                        event.ignore()
                        return
                    break
                # 誤検知のフラグはリセット
                try:
                    tab.editor.document().setModified(False)
                    tab.is_modified = False
                except Exception:
                    pass

        # FTP 接続が残っていれば QUIT 送信 + キープアライブタイマー停止 +
        # last_dir 永続化 をまとめて処理 (_disconnect が全部やってくれる)
        try:
            if getattr(self, 'ftp_panel', None) is not None and self.ftp_panel.ftp is not None:
                self.ftp_panel._disconnect()
        except Exception:
            pass

        # 開いているモードレスダイアログ (SQL抽出 / DB実行) も明示的に閉じる
        # (WA_DeleteOnClose 設定済みなので close() で安全に破棄される)
        try:
            for dlg in list(getattr(self, '_open_dialogs', [])):
                try:
                    dlg.close()
                except Exception:
                    pass
            db_dlg = getattr(self, '_db_dialog', None)
            if db_dlg is not None:
                try:
                    db_dlg.close()
                except Exception:
                    pass
        except Exception:
            pass

        event.accept()


# ---------------------------------------------------------------------------
# SQL抽出・整形ダイアログ
# ---------------------------------------------------------------------------

# ログ行ヘッダ (PID/レベル/日時) を取り除くプレフィックスパターン
# 例: "<2862093>[DBG]2024/07/04 13:03:46.656 Execute SELECT ..."
#     → "Execute SELECT ..." まで剥がす
_LOG_PREFIX_RE = re.compile(
    r'^\s*'
    r'(?:<\d+>\s*)?'                                                # <PID>
    # [YYYY/MM/DD HH:MM:SS.mmm][LEVEL][THREAD][Class#method():line] 形式の先頭ブラケット連鎖
    r'(?:\[\d{4}[-/]\d{2}[-/]\d{2}[ T]\d{1,2}:\d{2}:\d{2}(?:[.,]\d+)?\]\s*(?:\[[^\]]*\]\s*)*)?'
    r'(?:\[\w+\]\s*)?'                                              # [LEVEL]
    r'(?:\d{4}[-/]\d{2}[-/]\d{2}(?:[T ]\d{1,2}:\d{2}:\d{2}(?:[.,]\d+)?)?\s*)?'  # YYYY/MM/DD HH:MM:SS.mmm
    # 裸のレベル語 (ブラケット無し)。例: "2024-07-04 13:03:46 INFO Hibernate: ..."
    r'(?:(?:ERROR|CRITICAL|FATAL|SEVERE|WARN(?:ING)?|INFO(?:RMATION)?|DEBUG|TRACE|VERBOSE|FINE|FINER|FINEST|CONFIG)\s+)?',
    re.IGNORECASE,
)

# ログからSQLを抽出するための既知プレフィックスと継続行パターン
_SQL_PREFIXES = [
    r'Hibernate\s*:\s*',
    r'SQL\s*:\s*',
    r'==>\s*Preparing\s*:\s*',
    r'(?:Executing|Executed|Execute)\s+(?:query|statement|SQL)?\s*:?\s*',  # Execute, Executing, Executed
    r'JDBC\s*\[Query\]\s*:\s*',
    r'query\s*:\s*',
    r'statement\s*:\s*',
    r'native\s+query\s*:\s*',
]
# Hibernate / MyBatis パラメータバインド行
_PARAM_PATTERNS = [
    # Hibernate: binding parameter [1] as [INTEGER] - [42]
    re.compile(r'binding parameter \[(\d+)\] as \[\w+\] - \[(.+)\]', re.IGNORECASE),
    # MyBatis: ==> Parameters: val1(Type), val2(Type), ...
    re.compile(r'==> Parameters: (.+)'),
]
_SQL_START_KW = re.compile(
    r'\b(SELECT|INSERT\s+INTO|INSERT|UPDATE|DELETE\s+FROM|DELETE|WITH|MERGE|CALL)\b',
    re.IGNORECASE,
)
# SQL文の開始判定: 本文の「先頭」が SQL ステートメントで始まる場合のみ採用する。
# .search() で行中どこでもヒットさせると、ログ本文の "...History: #delete" のような
# 語尾が DELETE/INSERT 等に誤マッチして、ログ全体を1つのSQLとして飲み込んでしまうため。
_SQL_START_ANCHORED = re.compile(
    r'^(SELECT\b|INSERT\s+INTO\b|UPDATE\s+\w|DELETE\s+FROM\b|WITH\s+\w|MERGE\s+INTO\b|CALL\s+\w)',
    re.IGNORECASE,
)
_LOG_LINE_START = re.compile(
    r'^\s*\[\d{4}[-/]\d{2}[-/]\d{2}[ T]\d{1,2}:\d{2}:\d{2}|'  # [YYYY/MM/DD HH:MM:SS...] 先頭ブラケット日時
    r'^\s*<\d+>\s*(?:\[\w+\])?\s*\d{4}[-/]\d{2}[-/]\d{2}|'   # <PID>[LEVEL]YYYY/MM/DD
    r'^\s*\[\w+\]\s*\d{4}[-/]\d{2}[-/]\d{2}|'                # [LEVEL]YYYY/MM/DD
    r'^\s*\d{4}[-/]\d{2}[-/]\d{2}[T ]\d{2}:\d{2}:\d{2}|'     # YYYY-MM-DD HH:MM:SS
    r'^\s*\d{4}[-/]\d{2}[-/]\d{2}|'                          # YYYY-MM-DD
    r'^\s*\d{2}:\d{2}:\d{2}|'                                # HH:MM:SS at line start
    r'^\s*(?:ERROR|CRITICAL|FATAL|WARN(?:ING)?|INFO|DEBUG|TRACE)\b',  # 行頭のレベル単独
    re.IGNORECASE,
)


_SQLPARSE_AVAILABLE: bool | None = None


def _check_sqlparse() -> bool:
    """sqlparse の有無を一度だけチェックして結果をキャッシュ"""
    global _SQLPARSE_AVAILABLE
    if _SQLPARSE_AVAILABLE is None:
        try:
            import sqlparse  # noqa: F401
            _SQLPARSE_AVAILABLE = True
        except ImportError:
            _SQLPARSE_AVAILABLE = False
    return _SQLPARSE_AVAILABLE


def _split_top_level_commas(s: str) -> list[str]:
    """カッコ () とクォート '' "" を考慮してトップレベルのカンマで分割する。
    例: TO_DATE('a','b'), 'x,y'  → ["TO_DATE('a','b')", "'x,y'"]
    """
    parts: list[str] = []
    depth = 0
    in_squote = False
    in_dquote = False
    buf = []
    i = 0
    n = len(s)
    while i < n:
        c = s[i]
        if in_squote:
            buf.append(c)
            if c == "'":
                # '' は文字列内のエスケープ
                if i + 1 < n and s[i + 1] == "'":
                    buf.append(s[i + 1]); i += 2; continue
                in_squote = False
            i += 1; continue
        if in_dquote:
            buf.append(c)
            if c == '"':
                in_dquote = False
            i += 1; continue
        if c == "'":
            in_squote = True; buf.append(c); i += 1; continue
        if c == '"':
            in_dquote = True; buf.append(c); i += 1; continue
        if c in '([':
            depth += 1; buf.append(c); i += 1; continue
        if c in ')]':
            depth -= 1; buf.append(c); i += 1; continue
        if c == ',' and depth == 0:
            parts.append(''.join(buf).strip()); buf = []; i += 1; continue
        buf.append(c); i += 1
    if buf:
        parts.append(''.join(buf).strip())
    return parts


def _format_insert_pairs(sql: str) -> str | None:
    """INSERT INTO table (col,...) VALUES (val,...) を
    「列名 = 値」の対応表 (読み取り用) に整形する。
    解析できない (列数≠値数 / 複数行VALUES等) 場合は None を返す。
    """
    # INSERT INTO <table> ( <cols> ) VALUES ( <vals> )
    m = re.match(
        r'\s*INSERT\s+INTO\s+([^\s(]+)\s*\((.*?)\)\s*VALUES\s*\((.*)\)\s*;?\s*$',
        sql, re.IGNORECASE | re.DOTALL,
    )
    if not m:
        return None
    table = m.group(1).strip()
    cols = _split_top_level_commas(m.group(2))
    vals = _split_top_level_commas(m.group(3))
    if not cols or len(cols) != len(vals):
        return None   # 対応が取れない場合は通常整形に任せる
    width = max(len(c) for c in cols)
    lines = [f"-- INSERT INTO {table}  (列 = 値) — {len(cols)} 列"]
    for c, v in zip(cols, vals):
        lines.append(f"{c.ljust(width)} = {v}")
    return '\n'.join(lines)


def _try_format_sql(sql: str, indent: int, keyword_case: str,
                    insert_pairs: bool = True) -> str:
    # INSERT は「列 = 値」の対応表で表示すると、どの列に何が入るか一目で分かる
    # (DB実行は参照系のみ許可なので INSERT は確認用 = 実行可否は問わない)
    # insert_pairs=False の時は通常のSQL整形 (コピーして実行したい場合)
    if insert_pairs and re.match(r'\s*INSERT\s+INTO\b', sql, re.IGNORECASE):
        paired = _format_insert_pairs(sql)
        if paired:
            return paired

    if not _check_sqlparse():
        return sql   # 未インストール時は素のSQLを返す
    try:
        import sqlparse
        return sqlparse.format(
            sql,
            reindent=True,
            keyword_case=keyword_case,
            indent_width=indent,
            strip_whitespace=True,
            use_space_around_operators=True,
        )
    except Exception:
        return sql


def _extract_sql_from_log(log_text: str, extra_prefixes: list[str]) -> list[dict]:
    """
    ログテキストからSQLブロックを抽出し、
    [{'sql': str, 'params': dict, 'raw': str, 'lineno': int}] を返す。
    """
    prefix_re = re.compile(
        '|'.join(_SQL_PREFIXES + [re.escape(p) for p in extra_prefixes if p]),
        re.IGNORECASE,
    )

    lines = log_text.splitlines()
    results: list[dict] = []
    current_sql_parts: list[str] = []
    current_params: dict[int, str] = {}
    current_lineno = 0

    def flush():
        if current_sql_parts:
            raw = ' '.join(current_sql_parts)
            results.append({
                'sql': raw,
                'params': dict(current_params),
                'lineno': current_lineno,
            })
        current_sql_parts.clear()
        current_params.clear()

    for lineno, line in enumerate(lines, 1):
        stripped = line.strip()
        is_log_line_start = bool(_LOG_LINE_START.match(stripped))

        # パラメータバインド行を収集（現在のSQL用）
        if current_sql_parts:
            for ppat in _PARAM_PATTERNS:
                m = ppat.search(stripped)
                if m:
                    if ppat == _PARAM_PATTERNS[0]:
                        idx = int(m.group(1))
                        current_params[idx] = m.group(2)
                    else:
                        # MyBatis: val1(Type), val2(Type)...
                        parts = [p.strip() for p in m.group(1).split(',')]
                        for i, part in enumerate(parts, 1):
                            val = re.sub(r'\(\w+\)$', '', part).strip()
                            current_params[i] = val
                    break

        # ログ行ヘッダ (<PID>[LEVEL]DATE TIME) を剥がしてから SQL プレフィックスも剥がす
        body = _LOG_PREFIX_RE.sub('', stripped, count=1).strip()
        # SQL プレフィックス (Hibernate: など) があれば、それ以降を本文とする
        # (プレフィックス前に残ったログ語を確実に落とすため、後方一致で切り出す)
        pm = prefix_re.search(body)
        if pm:
            body = body[pm.end():].strip()

        if _SQL_START_ANCHORED.match(body) and is_log_line_start:
            # 新規SQL: 直前のSQL継続中なら一度確定してから新規スタート
            # (ログ行ヘッダ付きで本文が SQL で始まったときのみ新規扱い、SQL内の SELECT 等は無視)
            flush()
            current_lineno = lineno
            current_sql_parts.append(body)
        elif current_sql_parts:
            if is_log_line_start or not stripped:
                # 新しいログ行 (別の処理ログ) or 空行 → SQL終了
                flush()
            else:
                # SQL の継続行 (折り返し)
                current_sql_parts.append(body)
        elif _SQL_START_ANCHORED.match(body):
            # ログ行ヘッダなしで本文が SQL で始まる (Hibernate: の直後など)
            flush()
            current_lineno = lineno
            current_sql_parts.append(body)

    flush()
    return results


def _substitute_params(sql: str, params: dict) -> str:
    """? プレースホルダーをパラメータ値で置換"""
    if not params:
        return sql
    result = sql
    for i in sorted(params.keys()):
        val = params[i]
        # 数値以外はクォートで囲む
        quoted = val if re.match(r'^-?\d+(\.\d+)?$', val) else f"'{val}'"
        result = result.replace('?', quoted, 1)
    return result


# ---------------------------------------------------------------------------
# ログ → ソースファイル ジャンプ (エラー調査でソースまで辿る)
# ---------------------------------------------------------------------------

# 検索対象のソース拡張子 (クラス名のみの参照で候補ファイル名を組み立てる際に使う)
_SOURCE_EXTS = (
    'java', 'kt', 'scala', 'py', 'js', 'jsx', 'ts', 'tsx',
    'cpp', 'cxx', 'cc', 'c', 'hpp', 'hh', 'h', 'cs', 'go', 'rb', 'php',
)
_SRC_EXT_RE = '(?:' + '|'.join(_SOURCE_EXTS) + ')'
# 再帰検索でスキップするディレクトリ (ビルド成果物・VCS・依存物)
_SOURCE_SKIP_DIRS = {
    '.git', '.svn', '.hg', 'node_modules', '__pycache__', '.idea', '.vscode',
    'dist', 'build', 'out', 'bin', 'obj', '.gradle', 'venv', '.venv', 'target',
}

# 1) Class#method():line  例: WP50121Servlet#createValueList():995  (Java)
_REF_CLASS_METHOD = re.compile(r'\b([A-Za-z_]\w*)#(\w+)\s*\(\s*\)\s*:\s*(\d+)')
# 2) (File.ext:line)  Java/JS スタックトレースの括弧内  例: (WP50121Servlet.java:995)
_REF_PAREN_FILE = re.compile(
    r'\(([\w.$\-]+\.' + _SRC_EXT_RE + r')\s*:\s*(\d+)\)', re.IGNORECASE)
# 3) File.ext:line / File.ext:line N (C#)  例: utils.py:42  /  Foo.cs:line 88
_REF_FILE_LINE = re.compile(
    r'([\w./\\$\-]+\.' + _SRC_EXT_RE + r')\s*:\s*(?:line\s+)?(\d+)', re.IGNORECASE)
# 4) Class::method(  例: ReqCarrier::reqCarrierCurrentStatus()  (C++ / 行番号なし)
#    行番号が無いので、ファイル特定後にメソッド定義を検索してジャンプする。
_REF_CPP_METHOD = re.compile(r'\b([A-Za-z_]\w*)::([A-Za-z_]\w*)\s*\(')
# Java/C# スタックの完全修飾名: at com.foo.Bar.method(  /  at Ns.Cls.Method(
_REF_FQCN = re.compile(r'\bat\s+([\w.$]+)\.[\w$<>]+\s*\(', re.IGNORECASE)


def _extract_source_refs(text: str) -> list[dict]:
    """テキストから「ソース参照」を抽出する。
    返す各要素: {
      'raw': 表示用の生文字列, 'line': 行番号(int, 不明なら0),
      'filename': 検索すべきファイル名 (拡張子付き / 不明なら ''),
      'classname': クラス名 (拡張子不明時の検索用 / 無ければ ''),
      'method':   メソッド名 (行番号が無い時の定義検索用 / 無ければ ''),
      'fqcn': 完全修飾名 com.foo.Bar (パッケージ優先用 / 無ければ ''),
    }
    重複 (同じ filename/classname + line + method) は除去する。
    """
    refs: list[dict] = []
    seen: set[tuple] = set()

    def add(raw, line, filename='', classname='', method='', fqcn=''):
        key = ((filename or classname).lower(), line, method.lower())
        if key in seen:
            return
        seen.add(key)
        refs.append({'raw': raw.strip(), 'line': line, 'filename': filename,
                     'classname': classname, 'method': method, 'fqcn': fqcn})

    for line in text.splitlines():
        fqcn_m = _REF_FQCN.search(line)
        fqcn = fqcn_m.group(1) if fqcn_m else ''
        # 2) 括弧内 File.ext:line (スタックトレース)
        paren_spans = []
        for m in _REF_PAREN_FILE.finditer(line):
            paren_spans.append(m.span())
            add(m.group(0), int(m.group(2)),
                filename=os.path.basename(m.group(1)), fqcn=fqcn)
        # 3) 素の File.ext:line (括弧内で既に拾った範囲は除く)
        for m in _REF_FILE_LINE.finditer(line):
            if any(s <= m.start() and m.end() <= e for s, e in paren_spans):
                continue
            add(m.group(0), int(m.group(2)),
                filename=os.path.basename(m.group(1)))
        # 1) Class#method():line  (Java)
        for m in _REF_CLASS_METHOD.finditer(line):
            add(m.group(0), int(m.group(3)),
                classname=m.group(1), method=m.group(2))
        # 4) Class::method(  (C++ / 行番号なし) — メソッド定義を後で検索
        for m in _REF_CPP_METHOD.finditer(line):
            cls, mth = m.group(1), m.group(2)
            add(f"{cls}::{mth}()", 0, classname=cls, method=mth)

    return refs


def _resolve_source_file(ref: dict, source_dirs: list[str]) -> list[str]:
    """参照に対応するソースファイルの絶対パス候補を返す。
    - filename があればそのファイル名で、無ければ classname.<各拡張子> で再帰検索
    - fqcn (パッケージ) があれば、パスがパッケージ階層を含む候補を優先
    """
    if not source_dirs:
        return []
    targets = set()
    if ref.get('filename'):
        targets.add(ref['filename'].lower())
    elif ref.get('classname'):
        for e in _SOURCE_EXTS:
            targets.add(f"{ref['classname']}.{e}".lower())
    if not targets:
        return []

    hits: list[str] = []
    for root in source_dirs:
        if not root or not os.path.isdir(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in _SOURCE_SKIP_DIRS]
            for fn in filenames:
                if fn.lower() in targets:
                    hits.append(os.path.join(dirpath, fn))

    if len(hits) > 1 and ref.get('fqcn'):
        # パッケージ階層 (com/foo/...) を含むパスを優先
        pkg = ref['fqcn'].rsplit('.', 1)[0] if '.' in ref['fqcn'] else ''
        if pkg:
            pkg_path = pkg.replace('.', os.sep).lower()
            preferred = [h for h in hits if pkg_path in h.lower()]
            if preferred:
                return preferred
    return hits


# ---------------------------------------------------------------------------
# DB 実行ダイアログ — SSH 経由で sqlplus/mysql/psql 等を実行し SELECT 結果を取得
# ---------------------------------------------------------------------------

_DB_PROFILES_PATH = os.path.join(os.path.expanduser('~'), '.ssh_log_viewer_profiles.json')

# ヒアドキュメントの区切り EOF をシングルクォートで囲む (<<'EOF') ことで
# bash の変数展開を無効化する。Oracle の "M_CONDITION$RECIPE" のような
# テーブル名に含まれる $ がシェルに食われるのを防ぐ。
#
# Oracle はあえて CSV 出力一択。結果表示側に「横グリッド / 縦転置 / 1件詳細 /
# テキスト」の4モードがあるため、sqlplus 出力形式を分ける必要は無い。
# (旧 v1.1 では通常表示/CSV/縦表示の3プリセットを用意していた)
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
    """SQL*Plus 出力からクエリ結果だけを抽出する。
    - 起動バナー (SQL*Plus Release / Copyright / Connected to: 等) を除去
    - 行頭の `SQL>` プロンプトと multi-line 継続プロンプト (2, 3, ...) を除去
    - `Disconnected from Oracle ...` 以降の終了メッセージを除去
    - sqlplus 系出力でなければ無加工で返す
    - sqlplus と判定できれば、結果が空になっても空文字を返す
      (= 「0件」として後段の UI 側で扱えるようにする)
    """
    if not text:
        return text
    # sqlplus 出力の特徴が無ければ素通し
    is_sqlplus = ('SQL*Plus' in text) or ('SQL>' in text)
    if not is_sqlplus:
        return text

    lines = text.splitlines()
    result: list[str] = []
    in_query = False

    # 行頭の連続した "SQL>" や continuation prompts (空白+数字+空白) をまとめて除去
    prompt_re = re.compile(r'^(?:SQL>\s*|\s*\d+\s+)+')
    trailing_prompt_re = re.compile(r'\s*SQL>\s*$')
    # "SQL> Disconnected from ..." パターンを含む混在行から
    # Disconnected 部分を除去するための正規表現
    disconnect_strip_re = re.compile(r'\s*SQL>\s*Disconnected from.*$|\s*Disconnected from.*$')

    for line in lines:
        # 行末に Disconnected が混在しているケース (例:
        # "SQL> SQL>  2 ... 9 SQL> Disconnected from Oracle ...") に対応:
        # 行頭の プロンプト部分と末尾の Disconnected 以降を両方除去してから
        # 残りに意味があれば追加。残らないなら以降は打ち切り。
        if 'Disconnected from' in line:
            stripped = prompt_re.sub('', line)
            stripped = disconnect_strip_re.sub('', stripped)
            if stripped.strip():
                if in_query or 'SQL>' in line:
                    result.append(stripped.rstrip())
            break

        if not in_query:
            # 最初に SQL> が登場した行から結果開始
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

    # 前後の空行除去
    while result and not result[0].strip():
        result.pop(0)
    while result and not result[-1].strip():
        result.pop()

    # sqlplus 出力と判定できた場合、空でもそのまま空文字を返す
    # (UI側で「0件」表示にする)
    return '\n'.join(result)


def _load_db_profiles() -> dict:
    """ssh_log_viewer と共通の接続プロファイル設定ファイルを読み込む。"""
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


class DBExecuteDialog(QDialog):
    """SSH 接続したサーバーのシェル上で sqlplus 等を実行して SELECT 結果を取得する。

    - 接続情報は ssh_log_viewer 側のプロファイル (.ssh_log_viewer_profiles.json) を流用
    - DB実行コマンドは {SQL} プレースホルダ付きテンプレートでプロファイル毎に保存可能
    - 安全側: SELECT/WITH 以外で始まる文は確認ダイアログ
    """

    def __init__(self, sql: str, default_profile: str = '', parent=None,
                 navigator=None):
        super().__init__(parent)
        self.setWindowTitle("SQL 実行 (SSH経由)")
        self.setMinimumSize(900, 650)
        self.resize(1050, 720)
        # タイトルバーに 最小化/最大化 ボタンを表示する
        self.setWindowFlags(
            self.windowFlags()
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
        )
        self._initial_sql = sql
        self._default_profile = default_profile or ''
        self._profiles = _load_db_profiles()
        # ナビゲータ (SqlExtractDialog 等。get_sql_count / get_formatted_sql_at /
        # get_current_index / navigate_to を持つオブジェクト)
        self._navigator = navigator
        self._build_ui()
        self._refresh_profile_combo()
        self._update_nav_buttons()

    def _build_ui(self):
        main = QVBoxLayout()
        main.setSpacing(4)
        main.setContentsMargins(8, 8, 8, 8)

        # ─── プロファイル選択 ─────────────────────────────────────────────
        prof_row = QHBoxLayout()
        prof_row.setSpacing(6)
        prof_row.addWidget(QLabel("接続プロファイル:"))
        self.profile_combo = QComboBox()
        self.profile_combo.setMinimumWidth(240)
        self.profile_combo.currentTextChanged.connect(self._on_profile_changed)
        prof_row.addWidget(self.profile_combo)

        prof_row.addSpacing(6)
        # 折りたたみトグルボタン (デフォルト: 折りたたみ済)
        self.cmd_toggle_btn = QPushButton("▶ DB実行コマンド設定")
        self.cmd_toggle_btn.setToolTip(
            "DB実行コマンドのテンプレート編集欄を表示/非表示します。\n"
            "通常運用時は折りたたんで OK。プロファイル毎の DB実行コマンドが\n"
            "保存されていれば、ここを開かなくても実行できます。"
        )
        self.cmd_toggle_btn.setCheckable(True)
        self.cmd_toggle_btn.setChecked(False)
        self.cmd_toggle_btn.clicked.connect(self._toggle_cmd_section)
        prof_row.addWidget(self.cmd_toggle_btn)

        prof_row.addSpacing(6)
        prof_row.addWidget(QLabel("DBプリセット:"))
        self.preset_combo = QComboBox()
        self.preset_combo.addItem("（選択）")
        for name in _DB_CMD_PRESETS:
            self.preset_combo.addItem(name)
        self.preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        prof_row.addWidget(self.preset_combo)
        prof_row.addStretch()
        main.addLayout(prof_row, 0)

        # ─── DB実行コマンドテンプレート (折りたたみ可能) ─────────────────
        self.cmd_section = QWidget()
        cmd_section_layout = QVBoxLayout(self.cmd_section)
        cmd_section_layout.setContentsMargins(0, 0, 0, 0)
        cmd_section_layout.setSpacing(2)

        cmd_section_layout.addWidget(QLabel("DB実行コマンド (テンプレート, {SQL} を実SQLで置換):"))
        self.cmd_input = QPlainTextEdit()
        self.cmd_input.setFont(QFont("Consolas", 10))
        self.cmd_input.setMaximumHeight(110)
        self.cmd_input.setPlaceholderText(
            "例:  sqlplus -S USER/PASS@SID <<EOF\n"
            "     set pagesize 200 linesize 200;\n"
            "     {SQL};\n"
            "     exit\nEOF"
        )
        cmd_section_layout.addWidget(self.cmd_input)

        cmd_btn_row = QHBoxLayout()
        cmd_btn_row.addStretch()
        save_btn = QPushButton("コマンドをプロファイルに保存")
        save_btn.setToolTip("現在の接続プロファイルに DB実行コマンドテンプレートを保存します")
        save_btn.clicked.connect(self._save_cmd_to_profile)
        cmd_btn_row.addWidget(save_btn)
        cmd_section_layout.addLayout(cmd_btn_row)

        # デフォルトでは非表示
        self.cmd_section.setVisible(False)
        main.addWidget(self.cmd_section)

        # ─── SQL 入力 ────────────────────────────────────────────────────
        sql_header = QHBoxLayout()
        sql_header.addWidget(QLabel("実行する SQL (SELECT / WITH 推奨, 末尾の ; は不要):"))

        # ナビゲーション: SqlExtractDialog 由来の SQL リストを順次切替
        # <<  <  [番号入力 / 件数表示]  >  >>
        # (シンボル文字が描画フォントで欠ける環境向けに ASCII 表記)
        self.nav_first_btn = QPushButton("<<")
        self.nav_first_btn.setMinimumWidth(38)
        self.nav_first_btn.setToolTip("先頭のSQLへジャンプ (Ctrl+Home)")
        self.nav_first_btn.clicked.connect(self._nav_first)
        self.nav_prev_btn = QPushButton("<")
        self.nav_prev_btn.setMinimumWidth(34)
        self.nav_prev_btn.setToolTip("前のSQLへ (Ctrl+←)")
        self.nav_prev_btn.clicked.connect(self._nav_prev)

        # 直接入力: 番号スピンボックス (矢印は非表示、Enter で確定)
        self.nav_index_spin = QSpinBox()
        self.nav_index_spin.setMinimum(1)
        self.nav_index_spin.setMaximum(1)
        self.nav_index_spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.nav_index_spin.setFixedWidth(70)
        self.nav_index_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.nav_index_spin.setToolTip("SQL番号を直接入力 (Enter で確定)")
        self.nav_index_spin.editingFinished.connect(self._nav_jump_to_input)
        self.nav_total_lbl = QLabel("/ 1")
        self.nav_total_lbl.setStyleSheet("color:#a9b7c6;")

        self.nav_next_btn = QPushButton(">")
        self.nav_next_btn.setMinimumWidth(34)
        self.nav_next_btn.setToolTip("次のSQLへ (Ctrl+→)")
        self.nav_next_btn.clicked.connect(self._nav_next)
        self.nav_last_btn = QPushButton(">>")
        self.nav_last_btn.setMinimumWidth(38)
        self.nav_last_btn.setToolTip("末尾のSQLへジャンプ (Ctrl+End)")
        self.nav_last_btn.clicked.connect(self._nav_last)

        sql_header.addSpacing(8)
        sql_header.addWidget(self.nav_first_btn)
        sql_header.addWidget(self.nav_prev_btn)
        sql_header.addWidget(self.nav_index_spin)
        sql_header.addWidget(self.nav_total_lbl)
        sql_header.addWidget(self.nav_next_btn)
        sql_header.addWidget(self.nav_last_btn)

        # 互換用 (古い名前を参照しているコードがあれば動くように)
        self.nav_counter_lbl = self.nav_total_lbl

        # ショートカット
        from PyQt6.QtGui import QShortcut, QKeySequence as _QKS
        self._nav_sc_first = QShortcut(_QKS("Ctrl+Home"), self)
        self._nav_sc_first.activated.connect(self._nav_first)
        self._nav_sc_last = QShortcut(_QKS("Ctrl+End"), self)
        self._nav_sc_last.activated.connect(self._nav_last)
        self._nav_sc_prev = QShortcut(_QKS("Ctrl+Left"), self)
        self._nav_sc_prev.activated.connect(self._nav_prev)
        self._nav_sc_next = QShortcut(_QKS("Ctrl+Right"), self)
        self._nav_sc_next.activated.connect(self._nav_next)

        sql_header.addStretch()
        self.dry_run_chk = QCheckBox("ドライラン (生成コマンドのみ表示)")
        self.dry_run_chk.setToolTip("実行はせず、置換後のコマンド文字列を結果欄に表示します")
        sql_header.addWidget(self.dry_run_chk)
        main.addLayout(sql_header, 0)

        self.sql_input = QPlainTextEdit()
        self.sql_input.setFont(QFont("Consolas", 10))
        self.sql_input.setPlainText(self._initial_sql)
        # SQL入力欄: 入力可能を示す明るめの枠線で結果欄と区別
        self.sql_input.setObjectName("sqlInput")
        self.sql_input.setStyleSheet(
            f"QPlainTextEdit#sqlInput {{ border: 2px solid #4a90c8;"
            f" background:{_theme()['editor_bg']}; color:{_theme()['text']}; }}"
        )
        self.sql_input.setToolTip("ここが SQL 入力欄です (実行結果欄ではありません)")
        # SQL シンタックスハイライト (LogViewer/SqlExtract と同じ配色)
        try:
            self.sql_input_highlighter = SyntaxHighlighter(self.sql_input.document(), 'sql')
        except Exception:
            self.sql_input_highlighter = None
        main.addWidget(self.sql_input, 1)

        # ─── 実行ボタン行 ────────────────────────────────────────────────
        run_row = QHBoxLayout()
        self.run_btn = QPushButton("▶ 実行  (Ctrl+Enter)")
        self.run_btn.setToolTip("選択中のプロファイルへ SSH 接続し、テンプレートに SQL を埋め込んで実行します\n(Ctrl+Enter でも実行可)")
        self.run_btn.clicked.connect(self._execute)
        # 目立つ緑系の強調スタイル
        self.run_btn.setMinimumHeight(34)
        self.run_btn.setMinimumWidth(160)
        run_font = self.run_btn.font()
        run_font.setBold(True)
        run_font.setPointSize(max(10, run_font.pointSize() + 1))
        self.run_btn.setFont(run_font)
        self.run_btn.setStyleSheet(
            "QPushButton {"
            " background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #4caf50, stop:1 #2e7d32);"
            " color: #ffffff; border: 1px solid #1b5e20; border-radius: 4px;"
            " padding: 4px 18px;"
            "}"
            "QPushButton:hover {"
            " background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #66bb6a, stop:1 #388e3c);"
            " border: 1px solid #2e7d32;"
            "}"
            "QPushButton:pressed {"
            " background: #2e7d32; border: 1px solid #1b5e20;"
            "}"
            "QPushButton:disabled {"
            " background: #4a4a4a; color: #888; border: 1px solid #333;"
            "}"
        )
        # Ctrl+Enter で実行できるショートカットも提供
        from PyQt6.QtGui import QShortcut, QKeySequence as _QKS
        self._run_shortcut = QShortcut(_QKS("Ctrl+Return"), self)
        self._run_shortcut.activated.connect(self._execute)
        self._run_shortcut2 = QShortcut(_QKS("Ctrl+Enter"), self)
        self._run_shortcut2.activated.connect(self._execute)
        run_row.addWidget(self.run_btn)

        run_row.addWidget(QLabel("実行方式:"))
        self.exec_mode_combo = QComboBox()
        self.exec_mode_combo.addItem("SFTP一時スクリプト + bash -l (推奨)", "sftp")
        self.exec_mode_combo.addItem("bash -l + stdin", "stdin")
        self.exec_mode_combo.addItem("デフォルトシェルに直接投げる", "direct")
        self.exec_mode_combo.setToolTip(
            "推奨: SFTP一時スクリプト方式\n"
            "  /tmp に #!/bin/bash -l スクリプトを書いて実行 → 削除。\n"
            "  引用符/csh/heredoc等の全シェル問題を回避できる最も確実な方法。\n\n"
            "bash -l + stdin:\n"
            "  bash -l を起動して stdin にコマンドを流し込む。\n\n"
            "デフォルトシェルに直接:\n"
            "  リモートのデフォルトシェル (bash/csh等) にそのままコマンドを投げる。\n"
            "  csh/tcsh の場合は引用符問題が出る可能性あり。"
        )
        self.exec_mode_combo.setMinimumWidth(220)
        run_row.addWidget(self.exec_mode_combo)

        run_row.addStretch()
        self.status_lbl = QLabel("")
        self.status_lbl.setStyleSheet("color:#808080;")
        run_row.addWidget(self.status_lbl)
        main.addLayout(run_row, 0)

        # ─── オプション行 (2行目) ──────────────────────────────────────────
        opt_row = QHBoxLayout()
        opt_row.setSpacing(8)

        self.clean_output_chk = QCheckBox("結果のみ表示")
        self.clean_output_chk.setChecked(True)
        self.clean_output_chk.setToolTip(
            "sqlplus の banner / SQL> プロンプト / 接続切断メッセージ等を除去し、\n"
            "クエリ結果だけを表示します。\n"
            "OFFにすると生のSSH出力を表示 (デバッグ向け)"
        )
        opt_row.addWidget(self.clean_output_chk)

        opt_row.addSpacing(6)
        opt_row.addWidget(QLabel("上限件数:"))
        self.row_limit_combo = QComboBox()
        # 表示ラベル / 実際の値 (0 = 無制限)
        for label, value in (("100 件", 100), ("500 件", 500), ("1000 件", 1000),
                              ("5000 件", 5000), ("10000 件", 10000), ("無制限", 0)):
            self.row_limit_combo.addItem(label, value)
        # デフォルト 1000 件
        self.row_limit_combo.setCurrentIndex(2)
        self.row_limit_combo.setMinimumWidth(100)
        self.row_limit_combo.setToolTip(
            "結果を最大何件まで表示するか。\n"
            "上限超過時は表示を切り詰めて警告を出します。\n"
            "(SQL自体は全件実行されます。UI凍結防止用のクライアント側上限です)\n"
            "無制限は大量データで UI が固まる可能性があります"
        )
        opt_row.addWidget(self.row_limit_combo)

        opt_row.addSpacing(6)
        self.echo_cmd_chk = QCheckBox("送信コマンドも結果に表示")
        self.echo_cmd_chk.setToolTip("デバッグ用: 実際にSSH送信したコマンド文字列を結果欄の先頭に出力します")
        opt_row.addWidget(self.echo_cmd_chk)

        opt_row.addStretch()
        main.addLayout(opt_row, 0)

        # ─── 結果表示 ────────────────────────────────────────────────────
        result_header = QHBoxLayout()
        result_lbl = QLabel("実行結果 (読み取り専用):")
        result_lbl.setStyleSheet("color:#a9b7c6; font-weight:600;")
        result_header.addWidget(result_lbl)
        result_header.addStretch()

        # 縦表示モード用のレコードナビゲーション (1件詳細表示の時のみ可視)
        # シンボル文字が描画フォントで欠ける環境向けに ASCII (<<, <, >, >>) に変更
        self.rec_first_btn = QPushButton("<<")
        self.rec_first_btn.setMinimumWidth(36)
        self.rec_first_btn.setToolTip("先頭のレコード")
        self.rec_first_btn.clicked.connect(lambda: self._goto_record(0))
        self.rec_prev_btn = QPushButton("<")
        self.rec_prev_btn.setMinimumWidth(34)
        self.rec_prev_btn.setToolTip("前のレコード")
        self.rec_prev_btn.clicked.connect(lambda: self._goto_record(self._current_record - 1))
        self.rec_index_spin = QSpinBox()
        self.rec_index_spin.setMinimum(1)
        self.rec_index_spin.setMaximum(1)
        self.rec_index_spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.rec_index_spin.setFixedWidth(70)
        self.rec_index_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.rec_index_spin.editingFinished.connect(
            lambda: self._goto_record(self.rec_index_spin.value() - 1)
        )
        self.rec_total_lbl = QLabel("/ 1")
        self.rec_total_lbl.setStyleSheet("color:#a9b7c6;")
        self.rec_next_btn = QPushButton(">")
        self.rec_next_btn.setMinimumWidth(34)
        self.rec_next_btn.setToolTip("次のレコード")
        self.rec_next_btn.clicked.connect(lambda: self._goto_record(self._current_record + 1))
        self.rec_last_btn = QPushButton(">>")
        self.rec_last_btn.setMinimumWidth(36)
        self.rec_last_btn.setToolTip("末尾のレコード")
        self.rec_last_btn.clicked.connect(lambda: self._goto_record(self._record_count() - 1))
        for w in (self.rec_first_btn, self.rec_prev_btn, self.rec_index_spin,
                  self.rec_total_lbl, self.rec_next_btn, self.rec_last_btn):
            w.setVisible(False)
            result_header.addWidget(w)

        result_header.addSpacing(8)
        result_header.addWidget(QLabel("表示形式:"))
        self.view_mode_combo = QComboBox()
        self.view_mode_combo.addItem("📊 全件 (横・グリッド)", "grid")
        self.view_mode_combo.addItem("📋 全件 (縦・転置)", "vertical_all")
        self.view_mode_combo.addItem("🔍 1件詳細 (縦)", "vertical")
        self.view_mode_combo.addItem("テキスト", "text")
        self.view_mode_combo.setToolTip(
            "全件(横): 通常のグリッド表示。1行=1レコード、横スクロール\n"
            "全件(縦・転置): 列名を左ヘッダーに、各レコードを横方向の列として表示\n"
            "1件詳細(縦): 選択した1レコードのみを項目|値で縦表示 (◁▷で巡回)\n"
            "テキスト: 生の出力をそのまま表示"
        )
        self.view_mode_combo.currentIndexChanged.connect(self._on_view_mode_changed)
        result_header.addWidget(self.view_mode_combo)
        main.addLayout(result_header)

        # 縦表示モード時に表示するレコードのインデックス
        self._current_record: int = 0
        # 解析済み行列のキャッシュ (グリッド再描画 / 縦表示で再利用)
        self._parsed_rows: list[list[str]] = []

        # スタック: 0=テキスト / 1=グリッド
        self.result_stack = QStackedWidget()
        self.result_view = QPlainTextEdit()
        self.result_view.setFont(QFont("Consolas", 10))
        self.result_view.setReadOnly(True)
        self.result_view.setObjectName("resultView")
        self.result_view.setStyleSheet(
            "QPlainTextEdit#resultView { border: 1px dashed #666; background:#181818; }"
        )
        self.result_view.setToolTip("ここは実行結果表示欄です (読み取り専用 / SQL入力欄ではありません)")
        self.result_stack.addWidget(self.result_view)

        self.result_table = QTableWidget()
        self.result_table.setAlternatingRowColors(True)
        self.result_table.setSortingEnabled(False)  # データ投入時は OFF、後で ON
        # 読み取り専用 (ダブルクリックでも編集できなくする)
        self.result_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.result_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        # viewport (テーブル右側の空白領域含む) もダークに染める
        _t = _theme()
        self.result_table.setStyleSheet(
            f"QTableWidget {{ background:{_t['panel_bg']}; color:{_t['text']}; border:1px dashed {_t['border']};"
            f" gridline-color:{_t['border']}; alternate-background-color:{_t['control_bg']}; }}"
            f"QTableWidget QTableCornerButton::section {{ background:{_t['toolbar_bg']}; border:1px solid {_t['border']}; }}"
            f"QHeaderView {{ background:{_t['toolbar_bg']}; }}"
            f"QHeaderView::section {{ background:{_t['toolbar_bg']}; color:{_t['text']}; border:1px solid {_t['border']};"
            f" padding:2px 6px; font-weight:600; }}"
            # 縦/横ヘッダーともに緑系で視認性を上げる
            f"QHeaderView::section:horizontal {{ background:{_t['toolbar_bg']}; color:#4a9e4a;"
            f" font-weight:700; padding:2px 8px; }}"
            f"QHeaderView::section:vertical {{ background:{_t['toolbar_bg']}; color:#4a9e4a;"
            f" font-weight:700; padding:2px 8px; text-align:left; }}"
            f"QTableWidget::item:selected {{ background:{_t['selection']}; color:{_t['text']}; }}"
        )
        # viewport 自体のパレットもテーマ色で明示的に設定 (Qt 既定色を上書き)
        from PyQt6.QtGui import QPalette
        pal = self.result_table.viewport().palette()
        pal.setColor(QPalette.ColorRole.Base, QColor(_t['panel_bg']))
        pal.setColor(QPalette.ColorRole.AlternateBase, QColor(_t['control_bg']))
        pal.setColor(QPalette.ColorRole.Window, QColor(_t['panel_bg']))
        self.result_table.viewport().setPalette(pal)
        self.result_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        # 最終列が余白を埋めるようストレッチ
        self.result_table.horizontalHeader().setStretchLastSection(True)
        self.result_table.verticalHeader().setVisible(True)
        self.result_stack.addWidget(self.result_table)
        # 起動時はグリッド表示 (stack index 1 = result_table)
        self.result_stack.setCurrentIndex(1)
        main.addWidget(self.result_stack, 2)

        # 直近の出力を保持 (表示形式切替時にパースし直すため)
        self._last_output_text: str = ''

        # ─── 下部ボタン ──────────────────────────────────────────────────
        bottom = QHBoxLayout()
        copy_sql_btn = QPushButton("SQLをコピー")
        copy_sql_btn.setToolTip("上の SQL 入力欄の内容全てをクリップボードへ")
        copy_sql_btn.clicked.connect(self._copy_sql)
        copy_btn = QPushButton("結果をコピー")
        copy_btn.setToolTip("下の実行結果欄の内容全てをクリップボードへ")
        copy_btn.clicked.connect(self._copy_result)
        clear_btn = QPushButton("結果クリア")
        clear_btn.clicked.connect(lambda: self.result_view.clear())
        close_btn = QPushButton("閉じる")
        close_btn.clicked.connect(self.close)
        bottom.addWidget(copy_sql_btn)
        bottom.addWidget(copy_btn)
        bottom.addWidget(clear_btn)
        bottom.addStretch()
        bottom.addWidget(close_btn)
        main.addLayout(bottom, 0)

        self.setLayout(main)

        # テーマ適用 (SqlExtractDialog と同じダーク基調)
        t = _theme()
        self.setStyleSheet(f"""
            QDialog {{ background: {t['bg']}; }}
            QLabel  {{ color: {t['text']}; }}
            QPushButton {{ background:{t['control_bg']}; color:{t['text']}; border:none; padding:4px 10px; border-radius:2px; }}
            QPushButton:hover {{ background:{t['control_hover']}; }}
            QPushButton:disabled {{ color:{t['text_dim']}; }}
            QComboBox {{ background:{t['control_bg']}; color:{t['text']}; border:1px solid {t['border']}; padding:1px 3px; }}
            QComboBox QAbstractItemView {{ background:{t['panel_bg']}; color:{t['text']}; selection-background-color:{t['selection']}; }}
            QPlainTextEdit {{ background:{t['panel_bg']}; color:{t['text']}; border:1px solid {t['border']};
                             selection-background-color:{t['selection']}; }}
            QCheckBox {{ color:{t['text']}; spacing:5px; }}
            QCheckBox::indicator {{ width:15px; height:15px; border:1px solid {t['border']};
                                   background:{t['panel_bg']}; border-radius:3px; }}
            QCheckBox::indicator:hover {{ border:1px solid #4a90c8; }}
            QCheckBox::indicator:checked {{ background:#3a8e3a; border:1px solid #4caf50; }}
        """)

    # ─── 折りたたみトグル ─────────────────────────────────────────────────

    def _toggle_cmd_section(self):
        """DB実行コマンド編集セクションの表示/非表示を切り替える。"""
        visible = self.cmd_toggle_btn.isChecked()
        self.cmd_section.setVisible(visible)
        self.cmd_toggle_btn.setText(
            "▼ DB実行コマンド設定" if visible else "▶ DB実行コマンド設定"
        )

    # ─── SQL ナビゲーション (◁▷) ─────────────────────────────────────────

    def _nav_widgets(self):
        """ナビゲーション関連ウィジェットを一括で扱うためのヘルパー。"""
        return [
            self.nav_first_btn, self.nav_prev_btn,
            self.nav_index_spin, self.nav_total_lbl,
            self.nav_next_btn, self.nav_last_btn,
        ]

    def _update_nav_buttons(self):
        """ナビゲータの状態に応じてボタン/入力欄の有効/可視を更新。"""
        nav = self._navigator
        if nav is None or not hasattr(nav, 'get_sql_count'):
            for w in self._nav_widgets():
                w.setVisible(False)
            return
        total = nav.get_sql_count()
        idx = nav.get_current_index()
        if total <= 1 or idx < 0:
            for w in self._nav_widgets():
                w.setVisible(False)
            return
        for w in self._nav_widgets():
            w.setVisible(True)
        # スピンボックスは循環的な変更を避けるため signal を一時的にブロック
        self.nav_index_spin.blockSignals(True)
        self.nav_index_spin.setMinimum(1)
        self.nav_index_spin.setMaximum(total)
        self.nav_index_spin.setValue(idx + 1)
        self.nav_index_spin.blockSignals(False)
        self.nav_total_lbl.setText(f"/ {total}")
        self.nav_first_btn.setEnabled(idx > 0)
        self.nav_prev_btn.setEnabled(idx > 0)
        self.nav_next_btn.setEnabled(idx < total - 1)
        self.nav_last_btn.setEnabled(idx < total - 1)

    def _nav_set_index(self, new_idx: int):
        """ナビゲータを new_idx に移動して SQL 入力欄を差し替える。"""
        nav = self._navigator
        if nav is None:
            return
        total = nav.get_sql_count()
        if not (0 <= new_idx < total):
            return
        # 親ダイアログ側の選択も同期 (戻った時の表示一貫性のため)
        nav.navigate_to(new_idx)
        formatted, lineno = nav.get_formatted_sql_at(new_idx)
        self.sql_input.setPlainText(formatted)
        # 結果欄は前 SQL のものなので明示的にクリア
        self.result_view.clear()
        self.result_table.setRowCount(0)
        self.result_table.setColumnCount(0)
        self._last_output_text = ''
        self.status_lbl.setText(f"SQL を切り替え: {new_idx + 1} / {total} (log行 {lineno})")
        self._update_nav_buttons()

    def _nav_jump(self, delta: int):
        nav = self._navigator
        if nav is None:
            return
        self._nav_set_index(nav.get_current_index() + delta)

    def _nav_prev(self):
        self._nav_jump(-1)

    def _nav_next(self):
        self._nav_jump(+1)

    def _nav_first(self):
        self._nav_set_index(0)

    def _nav_last(self):
        nav = self._navigator
        if nav is None:
            return
        total = nav.get_sql_count()
        if total > 0:
            self._nav_set_index(total - 1)

    def _nav_jump_to_input(self):
        """直接入力された SQL 番号にジャンプ。1-based → 0-based 変換。"""
        nav = self._navigator
        if nav is None:
            return
        new_idx = self.nav_index_spin.value() - 1
        # 既に同じ位置ならスキップ (起動直後の editingFinished 等を吸収)
        if new_idx == nav.get_current_index():
            return
        self._nav_set_index(new_idx)

    # ─── プロファイル切り替え ─────────────────────────────────────────────

    def _refresh_profile_combo(self):
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        names = list(self._profiles.keys())
        for n in names:
            self.profile_combo.addItem(n)
        if self._default_profile and self._default_profile in self._profiles:
            self.profile_combo.setCurrentText(self._default_profile)
        elif names:
            self.profile_combo.setCurrentIndex(0)
        self.profile_combo.blockSignals(False)
        self._on_profile_changed(self.profile_combo.currentText())

    def _on_profile_changed(self, name: str):
        prof = self._profiles.get(name, {})
        cmd = prof.get('db_exec_cmd', '') or ''
        self.cmd_input.setPlainText(cmd)
        host = prof.get('host', '')
        user = prof.get('user', '')
        if host:
            self.status_lbl.setText(f"接続先: {user}@{host}")
        else:
            self.status_lbl.setText("プロファイル未選択")

    def _on_preset_changed(self, idx: int):
        if idx <= 0:
            return
        name = self.preset_combo.currentText()
        tmpl = _DB_CMD_PRESETS.get(name, '')
        if tmpl:
            self.cmd_input.setPlainText(tmpl)
            # プリセットを選んだら設定セクションを自動展開
            # (USER/PASS/SID を書き換えてもらう必要があるため)
            if not self.cmd_toggle_btn.isChecked():
                self.cmd_toggle_btn.setChecked(True)
                self._toggle_cmd_section()
        # 選択直後にリセット (繰り返しプリセット指定を可能にする)
        self.preset_combo.blockSignals(True)
        self.preset_combo.setCurrentIndex(0)
        self.preset_combo.blockSignals(False)

    def _save_cmd_to_profile(self):
        name = self.profile_combo.currentText()
        if not name or name not in self._profiles:
            QMessageBox.warning(self, "プロファイル未選択",
                "保存先の接続プロファイルが選択されていません。")
            return
        self._profiles[name]['db_exec_cmd'] = self.cmd_input.toPlainText()
        _save_db_profiles(self._profiles)
        self.status_lbl.setText(f"保存しました: {name}")

    # ─── 実行 ─────────────────────────────────────────────────────────────

    # 読み取り専用ホワイトリスト (これ以外の SQL は実行をブロック)
    _READ_ONLY_KEYWORDS = frozenset({'SELECT', 'WITH', 'EXPLAIN', 'DESC', 'DESCRIBE', 'SHOW'})
    # 更新系のキーワード (検出用)
    _MODIFY_KEYWORDS = frozenset({
        'INSERT', 'UPDATE', 'DELETE', 'MERGE', 'TRUNCATE',
        'DROP', 'CREATE', 'ALTER', 'RENAME',
        'GRANT', 'REVOKE',
        'COMMIT', 'ROLLBACK', 'SAVEPOINT', 'SET',
        'LOCK', 'CALL', 'EXEC', 'EXECUTE', 'BEGIN', 'DECLARE',
    })

    def _strip_leading_comments(self, sql: str) -> str:
        """SQL 先頭の -- 行コメントと /* */ ブロックコメントを剥がす。"""
        s = sql.lstrip()
        while True:
            if s.startswith('--'):
                nl = s.find('\n')
                s = s[nl + 1:] if nl >= 0 else ''
                s = s.lstrip()
                continue
            if s.startswith('/*'):
                end = s.find('*/')
                s = s[end + 2:] if end >= 0 else ''
                s = s.lstrip()
                continue
            break
        return s

    def _first_keyword(self, sql: str) -> str:
        """SQL 先頭の英単語を大文字で返す。コメント除去後に判定。"""
        s = self._strip_leading_comments(sql)
        m = re.match(r'(\w+)', s)
        return m.group(1).upper() if m else ''

    def _strip_sql_strings_and_comments(self, sql: str) -> str:
        """SQL から文字列リテラルとコメントを除去 (検査用)。
        FOR UPDATE などのキーワード検出時に、コメントや文字列内のヒットで
        偽陽性を起こさないようにする。
        """
        # 行コメント -- ... 改行
        s = re.sub(r'--[^\n]*', ' ', sql)
        # ブロックコメント /* ... */
        s = re.sub(r'/\*.*?\*/', ' ', s, flags=re.DOTALL)
        # 文字列リテラル '...' ('' のエスケープを含む簡易処理)
        s = re.sub(r"'(?:[^']|'')*'", "''", s)
        # 識別子クォート "..." (Oracle/PostgreSQL)
        s = re.sub(r'"(?:[^"]|"")*"', '""', s)
        return s

    def _detect_locking_clause(self, sql: str) -> str:
        """SELECT ... FOR UPDATE / FOR SHARE 等のロック取得句を検出する。
        検出した場合は表示用の文字列を返す。検出しなければ ''。
        """
        cleaned = self._strip_sql_strings_and_comments(sql)
        # FOR UPDATE / FOR SHARE / FOR KEY SHARE / FOR NO KEY UPDATE
        patterns = [
            (r'\bFOR\s+UPDATE\b(?:\s+OF\s+\w+(?:\s*,\s*\w+)*)?'
             r'(?:\s+(?:NOWAIT|WAIT\s+\d+|SKIP\s+LOCKED))?', 'FOR UPDATE'),
            (r'\bFOR\s+SHARE\b', 'FOR SHARE'),
            (r'\bFOR\s+KEY\s+SHARE\b', 'FOR KEY SHARE'),
            (r'\bFOR\s+NO\s+KEY\s+UPDATE\b', 'FOR NO KEY UPDATE'),
        ]
        for pat, label in patterns:
            m = re.search(pat, cleaned, re.IGNORECASE)
            if m:
                return f"{label} (位置: '{m.group(0)}')"
        return ''

    def _execute(self):
        sql_raw = self.sql_input.toPlainText().strip()
        sql = sql_raw.rstrip(';').strip()
        if not sql:
            QMessageBox.warning(self, "SQL 未入力", "実行する SQL を入力してください。")
            return

        # 安全性チェック: 読み取り系以外は実行を完全ブロック
        first_word = self._first_keyword(sql)
        if first_word not in self._READ_ONLY_KEYWORDS:
            # 種別を分かりやすく案内
            if first_word in self._MODIFY_KEYWORDS:
                reason = f"更新系の SQL です (先頭: {first_word})。"
            elif first_word:
                reason = f"未知/許可されていない先頭キーワードです (先頭: {first_word})。"
            else:
                reason = "SQL の先頭キーワードを検出できません。"
            QMessageBox.critical(
                self, "実行ブロック",
                "⛔ 参照系以外の SQL は実行できません。\n\n"
                f"{reason}\n\n"
                "本ツールでは安全のため、以下の先頭キーワードのみ許可しています:\n"
                "    SELECT / WITH / EXPLAIN / DESC / DESCRIBE / SHOW\n\n"
                "INSERT / UPDATE / DELETE / MERGE / DDL 等は実行できません。\n"
                "更新が必要な場合は別ツール (SQL*Plus を直接 SSH ターミナル等) で\n"
                "管理者承認のもと実施してください。"
            )
            return

        # 追加チェック: SELECT FOR UPDATE / FOR SHARE 等のロック取得もブロック
        # (他トランザクションをブロックして本番影響を出す恐れがあるため)
        lock_match = self._detect_locking_clause(sql)
        if lock_match:
            QMessageBox.critical(
                self, "実行ブロック",
                "⛔ 行ロックを取得する SELECT は実行できません。\n\n"
                f"検出: {lock_match}\n\n"
                "FOR UPDATE / FOR SHARE 等は対象行に排他/共有ロックを掛けるため、\n"
                "他トランザクションをブロックして本番障害の原因になり得ます。\n"
                "純粋な参照のみが許可されています。\n\n"
                "対処: 該当句を削除してください\n"
                "  例)  SELECT ... FOR UPDATE   →   SELECT ...\n"
                "ロック取得が必要な場合は別ツールで管理者承認のもと実施してください。"
            )
            return

        cmd_template = self.cmd_input.toPlainText().strip()
        if not cmd_template:
            QMessageBox.warning(self, "コマンド未設定",
                "DB実行コマンドテンプレートを入力してください。\n"
                "右上の「DBプリセット」から雛形を選べます。")
            return
        if '{SQL}' not in cmd_template:
            QMessageBox.warning(self, "テンプレートエラー",
                "コマンドテンプレートに {SQL} プレースホルダーが含まれていません。")
            return

        # SQL 内のダブルクォートをエスケープ (シェル展開対策)
        escaped_sql = sql.replace('\\', '\\\\').replace('"', '\\"')
        # 改行は LF に正規化 (CRLF だと heredoc の終端 EOF が一致しない)
        escaped_sql = escaped_sql.replace('\r\n', '\n').replace('\r', '\n')
        # SQL*Plus は既定で空行を文末扱いするため SQL 中の空行 (空白のみ含む)
        # を全部除去する。整形時の見栄え用の空行であってセマンティクスは
        # 変わらない。他DB (mysql/psql/sqlite等) でも問題なし。
        escaped_sql = re.sub(r'(?m)^[ \t]*\n', '', escaped_sql)
        cmd_body = cmd_template.replace('{SQL}', escaped_sql)
        # テンプレート自体の CRLF も除去
        cmd_body = cmd_body.replace('\r\n', '\n').replace('\r', '\n')
        # 安全弁: heredoc が <<EOF (クォート無し) になっていると bash が
        # $RECIPE 等の変数を展開してしまうため、自動で <<'EOF' に補正する。
        # 既に <<'EOF' / <<"EOF" / <<-EOF 等になっていればそのまま。
        cmd_body = re.sub(
            r'(<<-?)([A-Za-z_][A-Za-z0-9_]*)(\s*\n)',
            lambda m: f"{m.group(1)}'{m.group(2)}'{m.group(3)}",
            cmd_body,
        )
        # 安全弁: sqlplus を呼ぶテンプレートで `set sqlblanklines on` が
        # 無いと SQL 中の空行で文が切れる。heredoc 開始直後に挿入する。
        if 'sqlplus' in cmd_body and 'sqlblanklines' not in cmd_body.lower():
            cmd_body = re.sub(
                r"(<<-?'?[A-Za-z_][A-Za-z0-9_]*'?\s*\n)",
                r"\1set sqlblanklines on define off\n",
                cmd_body,
                count=1,
            )
        # 安全弁: `set markup csv on quote off` だとデータ値内の `,` で
        # CSV パースが崩れるため、自動で `quote on` に補正する。
        cmd_body = re.sub(
            r'(?i)(set\s+markup\s+csv\s+on\s+quote\s+)off\b',
            r'\1on',
            cmd_body,
        )

        exec_mode = self.exec_mode_combo.currentData() or "sftp"

        if self.dry_run_chk.isChecked():
            if exec_mode == "sftp":
                dry = (
                    "[DRY RUN] 実行方式: SFTP一時スクリプト + bash -l\n\n"
                    "  /tmp/sora_db_exec_<timestamp>.sh を作成し中身は以下:\n"
                    "----- ↓ script ↓ -----\n"
                    "#!/bin/bash --login\n"
                    "set -o pipefail\n"
                    f"{cmd_body}\n"
                    "----- ↑ script ↑ -----\n\n"
                    "  実行: bash --login /tmp/sora_db_exec_xxx.sh"
                )
            elif exec_mode == "stdin":
                dry = (
                    "[DRY RUN] 実行方式: bash -l + stdin\n\n"
                    "  exec_command: bash -l\n"
                    "  stdin:\n"
                    "----- ↓ stdin ↓ -----\n"
                    f"{cmd_body}\n"
                    "----- ↑ stdin ↑ -----"
                )
            else:
                dry = (
                    "[DRY RUN] 実行方式: デフォルトシェルに直接\n\n"
                    "  exec_command:\n"
                    f"{cmd_body}"
                )
            self._set_result_text(dry)
            self.status_lbl.setText("ドライラン完了")
            return

        prof_name = self.profile_combo.currentText()
        prof = self._profiles.get(prof_name)
        if not prof:
            QMessageBox.warning(self, "プロファイル未選択",
                "接続プロファイルを選択してください。")
            return

        try:
            import paramiko
        except ImportError:
            QMessageBox.critical(self, "paramiko 未インストール",
                "SSH 接続には paramiko が必要です:\n    pip install paramiko")
            return

        self.run_btn.setEnabled(False)
        self.status_lbl.setText(f"実行中: {prof_name} ...")
        self.result_view.setPlainText(f"-- 接続中: {prof_name} --\n")
        # 接続中は中間状態なので _last_output_text は更新しない
        QApplication.processEvents()

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

            # ─── モード別に実行 ───────────────────────────────────────────
            if exec_mode == "sftp":
                # SFTP で /tmp に一時スクリプトを書き込み bash -l で実行
                import time as _time
                script_path = f"/tmp/sora_db_exec_{int(_time.time() * 1000)}_{os.getpid()}.sh"
                script_content = (
                    "#!/bin/bash --login\n"
                    "set -o pipefail\n"
                    + cmd_body
                    + ("\n" if not cmd_body.endswith("\n") else "")
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

                run_cmd = f"bash --login {script_path}"
                stdin_ch, stdout, stderr = client.exec_command(
                    run_cmd, timeout=180, get_pty=False
                )
                out = stdout.read().decode('utf-8', errors='replace')
                err = stderr.read().decode('utf-8', errors='replace')
                exit_code = stdout.channel.recv_exit_status()
                sent_cmd = run_cmd

            elif exec_mode == "stdin":
                sent_cmd = "bash -l"
                stdin_ch, stdout, stderr = client.exec_command(
                    sent_cmd, timeout=180, get_pty=False
                )
                stdin_ch.write(cmd_body)
                if not cmd_body.endswith('\n'):
                    stdin_ch.write('\n')
                stdin_ch.flush()
                try:
                    stdin_ch.channel.shutdown_write()
                except Exception:
                    pass
                out = stdout.read().decode('utf-8', errors='replace')
                err = stderr.read().decode('utf-8', errors='replace')
                exit_code = stdout.channel.recv_exit_status()

            else:  # direct
                sent_cmd = cmd_body
                stdin_ch, stdout, stderr = client.exec_command(
                    sent_cmd, timeout=180, get_pty=False
                )
                out = stdout.read().decode('utf-8', errors='replace')
                err = stderr.read().decode('utf-8', errors='replace')
                exit_code = stdout.channel.recv_exit_status()

            # 出力後処理 (sqlplus banner / プロンプト / 切断メッセージを除去)
            clean = self.clean_output_chk.isChecked()
            display_out = _clean_sqlplus_output(out) if clean else out

            # 上限件数の適用 (UI凍結防止のクライアント側カット)
            row_limit = self.row_limit_combo.currentData() or 0
            truncated_count = 0
            if row_limit > 0 and display_out:
                lines = display_out.splitlines()
                # CSV っぽい場合は 1行目=ヘッダーなので +1 行確保
                has_csv_header = (
                    len(lines) >= 1
                    and ',' in lines[0]
                    and not lines[0].strip().startswith('-')
                )
                keep_lines = row_limit + (1 if has_csv_header else 0)
                if len(lines) > keep_lines:
                    truncated_count = len(lines) - keep_lines
                    display_out = '\n'.join(lines[:keep_lines])

            parts = []
            if self.echo_cmd_chk.isChecked():
                parts.append(f"-- [実行方式: {exec_mode}] --")
                parts.append(f"-- [SSH exec_command] --")
                parts.append(sent_cmd)
                if exec_mode == "sftp" and script_path:
                    parts.append(f"-- [一時スクリプト: {script_path}] --")
                    parts.append(script_content)
                elif exec_mode == "stdin":
                    parts.append("-- [stdin に流し込んだ本体] --")
                    parts.append(cmd_body)
                parts.append("")
            if clean:
                # クリーンモードでは見出しを最小限に
                if display_out.strip():
                    parts.append(display_out.rstrip())
                else:
                    parts.append("⚠ 0 件 / 該当データなし (SQLは正常完了)")
                if truncated_count > 0:
                    parts.append(
                        f"\n⚠ 表示を上限 {row_limit} 件で切り詰めました "
                        f"(残り {truncated_count} 行は非表示)。\n"
                        f"   全件確認したい場合は『上限件数』を増やすか、"
                        f"SQL側で ROWNUM/FETCH FIRST で絞ってください。"
                    )
                if err.strip():
                    parts.append("\n-- [STDERR] --")
                    parts.append(err.rstrip())
                if exit_code != 0:
                    parts.append(f"\n-- exit code: {exit_code} --")
            else:
                parts.append("-- [STDOUT] --")
                parts.append(out.rstrip() if out.strip() else "(空)")
                if truncated_count > 0:
                    parts.append(
                        f"\n⚠ 表示を上限 {row_limit} 件で切り詰めました "
                        f"(残り {truncated_count} 行は非表示)。"
                    )
                parts.append("\n-- [STDERR] --")
                parts.append(err.rstrip() if err.strip() else "(空)")
                parts.append(f"\n-- exit code: {exit_code} --")
            if not out.strip() and not err.strip():
                parts.append(
                    "\n💡 出力が両方とも空です。考えられる原因:\n"
                    "  ・sqlplus が PATH に無い (.bash_profile/.bashrc を確認)\n"
                    "  ・接続文字列 (USER/PASS@SID) が無効\n"
                    "  ・「送信コマンドも結果に表示」を ON にして詳細確認\n"
                    "  ・別の「実行方式」を試す"
                )
            # テキスト欄は echo/clean を尊重した連結結果を表示。
            # グリッドは "実際のSQL出力のみ" を解析対象にする (送信コマンドや
            # banner 等のメタ情報はグリッド化されないようにする)。
            full_text = '\n'.join(parts)
            grid_source = display_out  # 常にクエリ出力本体だけを使う
            self._last_output_text = grid_source
            self.result_view.setPlainText(full_text)
            if self.view_mode_combo.currentData() == "grid":
                self._render_grid(grid_source)

            # ステータスバーにも 0件 / 件数 を明示
            row_hint = ""
            if exit_code == 0:
                if not display_out.strip():
                    row_hint = " · ⚠ 0 件"
                else:
                    # CSV ぽければ data 行数 (header除く) を表示
                    parsed = self._parse_csv_lines(display_out)
                    if len(parsed) >= 2:
                        row_hint = f" · {len(parsed) - 1} 件"
            if truncated_count > 0:
                row_hint += f" · ⚠ {truncated_count} 行切り詰め"
            self.status_lbl.setText(
                f"完了 (exit={exit_code}): {prof_name}{row_hint}"
                if exit_code == 0 else
                f"エラー (exit={exit_code}): {prof_name}"
            )

            # 一時スクリプト削除
            if script_path:
                try:
                    sftp = client.open_sftp()
                    sftp.remove(script_path)
                    sftp.close()
                except Exception:
                    pass
        except Exception as e:
            self._set_result_text(f"接続/実行エラー:\n{e}")
            self.status_lbl.setText("エラー")
        finally:
            try:
                if client is not None:
                    client.close()
            except Exception:
                pass
            self.run_btn.setEnabled(True)

    def _copy_result(self):
        text = self.result_view.toPlainText()
        if text:
            QApplication.clipboard().setText(text)
            self.status_lbl.setText("結果をクリップボードにコピーしました")

    def _copy_sql(self):
        text = self.sql_input.toPlainText()
        if text:
            QApplication.clipboard().setText(text)
            self.status_lbl.setText("SQL をクリップボードにコピーしました")

    # ─── 表示形式切替 / グリッド描画 ─────────────────────────────────────

    def _on_view_mode_changed(self, idx: int):
        mode = self.view_mode_combo.currentData()
        # レコードナビゲーションは 1件詳細 モードの時のみ可視
        nav_visible = (mode == "vertical")
        for w in (self.rec_first_btn, self.rec_prev_btn, self.rec_index_spin,
                  self.rec_total_lbl, self.rec_next_btn, self.rec_last_btn):
            w.setVisible(nav_visible)

        text = self._last_output_text or self.result_view.toPlainText()
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

    def _set_result_text(self, text: str):
        """テキスト/グリッド両方の表示を更新する。"""
        self._last_output_text = text
        self.result_view.setPlainText(text)
        # 現在の表示形式に応じて再描画
        mode = self.view_mode_combo.currentData()
        if mode == "grid":
            self._render_grid(text)
        elif mode == "vertical_all":
            self._render_vertical_all(text)
        elif mode == "vertical":
            self._render_vertical(text)

    def _parse_csv_lines(self, text: str) -> list[list[str]]:
        """テキストから CSV または固定幅表形式を行列にパースする。
        - 全体に `,` を含み CSV として読めれば csv.reader で読む
          (`"..."` 内の改行を1フィールドとして正しく扱うため、テキスト全体を
          そのまま投入する)
        - CSV っぽくなければ空白2個以上で分割を試みる (sqlplus 通常表示)
        - 先頭の `-- ...` などのコメント風行はスキップ
        """
        import csv
        from io import StringIO

        if not text or not text.strip():
            return []

        # 先頭のコメント/ノイズ行を剥がす (csv.reader に渡る前の前処理)
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

        # CSV 判定: 含まれる `,` 数で雑に判定 (全文に対して)
        if clean_text.count(',') >= 1:
            try:
                reader = csv.reader(StringIO(clean_text))
                rows = [row for row in reader if row]   # 空行は除外
                # CSV として 2 列以上に分かれていれば成功とみなす
                max_cols = max((len(r) for r in rows), default=0)
                if max_cols >= 2:
                    return rows
            except Exception:
                pass

        # フォールバック: 空白2個以上で分割 (sqlplus 表形式の超ざっくり対応)
        rows: list[list[str]] = []
        for line in clean_text.splitlines():
            if not line.strip():
                continue
            cells = re.split(r' {2,}|\t+', line.strip())
            rows.append(cells)
        return rows

    def _render_grid(self, text: str):
        """テキストをパースしてグリッドに描画。"""
        self.result_table.setSortingEnabled(False)
        self.result_table.clear()

        def show_message(msg: str, color: str = "#e0a96b"):
            """グリッドに1セルだけのメッセージ行を表示する。"""
            self.result_table.setColumnCount(1)
            self.result_table.setHorizontalHeaderLabels(["メッセージ"])
            self.result_table.setRowCount(1)
            item = QTableWidgetItem(msg)
            item.setForeground(QColor(color))
            font = item.font()
            font.setBold(True)
            item.setFont(font)
            self.result_table.setItem(0, 0, item)
            self.result_table.resizeColumnsToContents()

        if not text or not text.strip():
            show_message("⚠ 0 件 / 該当データなし (SQLは正常完了)")
            return

        rows = self._parse_csv_lines(text)
        if not rows:
            show_message("⚠ 0 件 / 該当データなし (SQLは正常完了)")
            return

        # 1行しかなくヘッダーのみの可能性 (CSV ヘッダー + 0データ行)
        if len(rows) == 1:
            # 列名は確かに取れているがデータが無い
            ncols = len(rows[0])
            self.result_table.setColumnCount(ncols)
            self.result_table.setHorizontalHeaderLabels(
                [h.strip() or f"col{i+1}" for i, h in enumerate(rows[0])]
            )
            self.result_table.setRowCount(1)
            placeholder = QTableWidgetItem("⚠ 0 件 / 該当データなし")
            placeholder.setForeground(QColor("#e0a96b"))
            f = placeholder.font(); f.setBold(True); placeholder.setFont(f)
            self.result_table.setItem(0, 0, placeholder)
            if ncols > 1:
                self.result_table.setSpan(0, 0, 1, ncols)
            self.result_table.resizeColumnsToContents()
            return

        # 最大列数に合わせる
        ncols = max(len(r) for r in rows)
        if ncols == 0:
            show_message("⚠ 0 件 / 該当データなし (SQLは正常完了)")
            return

        # 1行目をヘッダーとして使う
        header = rows[0] + [''] * (ncols - len(rows[0]))
        body = rows[1:]

        self.result_table.setColumnCount(ncols)
        self.result_table.setHorizontalHeaderLabels([h.strip() or f"col{i+1}" for i, h in enumerate(header)])
        self.result_table.setRowCount(len(body))
        for r, row in enumerate(body):
            for c in range(ncols):
                val = row[c] if c < len(row) else ''
                item = QTableWidgetItem(val)
                self.result_table.setItem(r, c, item)
        self.result_table.resizeColumnsToContents()
        # 過剰に広い列は上限を設定
        for c in range(ncols):
            if self.result_table.columnWidth(c) > 400:
                self.result_table.setColumnWidth(c, 400)
        self.result_table.setSortingEnabled(True)
        # 縦表示モード用に解析結果をキャッシュ
        self._parsed_rows = rows

    # ─── 1件詳細 (縦表示) モード ─────────────────────────────────────────

    def _record_count(self) -> int:
        """データレコード数 (ヘッダーを除く)。"""
        if not self._parsed_rows or len(self._parsed_rows) < 2:
            return 0
        return len(self._parsed_rows) - 1

    def _update_record_nav(self):
        """レコードナビゲーション (番号入力欄/ボタン群) を現在の状態に同期。"""
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
        """指定レコードに移動して縦表示を再描画 + ナビゲーション更新。"""
        total = self._record_count()
        if total <= 0:
            return
        idx = max(0, min(idx, total - 1))
        self._current_record = idx
        self._render_vertical_current()
        self._update_record_nav()

    def _render_vertical_all(self, text: str):
        """全レコードを転置して表示 (列名=縦ヘッダー、各レコード=横列)。"""
        self.result_table.setSortingEnabled(False)
        # 一度クリアしてから新規プロパティを設定
        self.result_table.clear()
        self.result_table.setRowCount(0)
        self.result_table.setColumnCount(0)

        rows = self._parse_csv_lines(text) if text and text.strip() else []
        self._parsed_rows = rows

        if not rows:
            self.result_table.setColumnCount(1)
            self.result_table.setHorizontalHeaderLabels(["メッセージ"])
            self.result_table.setRowCount(1)
            item = QTableWidgetItem("⚠ 0 件 / 該当データなし (SQLは正常完了)")
            item.setForeground(QColor("#e0a96b"))
            f = item.font(); f.setBold(True); item.setFont(f)
            self.result_table.setItem(0, 0, item)
            self.result_table.resizeColumnsToContents()
            return

        header = rows[0]
        body = rows[1:]
        n_fields = len(header)
        n_records = len(body)

        if n_records == 0:
            # ヘッダーのみあってデータが無い場合
            self.result_table.setRowCount(n_fields)
            self.result_table.setColumnCount(1)
            self.result_table.setVerticalHeaderLabels(
                [(h or '').strip() or f"col{i+1}" for i, h in enumerate(header)]
            )
            self.result_table.setHorizontalHeaderLabels(["値"])
            for i in range(n_fields):
                ph = QTableWidgetItem("⚠ 0 件 / 該当データなし")
                ph.setForeground(QColor("#e0a96b"))
                f = ph.font(); f.setBold(True); ph.setFont(f)
                self.result_table.setItem(i, 0, ph)
            self.result_table.resizeColumnsToContents()
            return

        # 転置: 行 = フィールド数、列 = レコード数
        self.result_table.setRowCount(n_fields)
        self.result_table.setColumnCount(n_records)
        # 縦ヘッダーに列名 / 横ヘッダーにレコード番号
        self.result_table.setVerticalHeaderLabels(
            [(h or '').strip() or f"col{i+1}" for i, h in enumerate(header)]
        )
        self.result_table.setHorizontalHeaderLabels(
            [f"#{i + 1}" for i in range(n_records)]
        )
        # 各レコードを 1 列ぶんずつ流し込む
        for col_idx, record in enumerate(body):
            for row_idx in range(n_fields):
                val = record[row_idx] if row_idx < len(record) else ''
                self.result_table.setItem(row_idx, col_idx, QTableWidgetItem(val))

        self.result_table.resizeColumnsToContents()
        # 各列の上限を 400px に
        for c in range(n_records):
            if self.result_table.columnWidth(c) > 400:
                self.result_table.setColumnWidth(c, 400)

    def _render_vertical(self, text: str):
        """テキストを解析して 1件詳細 (縦) モードで描画。"""
        rows = self._parse_csv_lines(text) if text and text.strip() else []
        self._parsed_rows = rows
        total = self._record_count()
        if self._current_record >= total:
            self._current_record = max(0, total - 1)
        self._render_vertical_current()
        self._update_record_nav()

    def _render_vertical_current(self):
        """現在の _current_record だけを 全件(縦・転置) と同じ構造で描画。
        縦ヘッダー = 列名、横ヘッダー = #N (現在のレコード番号)、1列のみ。
        """
        self.result_table.setSortingEnabled(False)
        self.result_table.clear()
        self.result_table.setRowCount(0)
        self.result_table.setColumnCount(0)
        rows = self._parsed_rows

        if not rows or len(rows) < 1:
            self.result_table.setColumnCount(1)
            self.result_table.setHorizontalHeaderLabels(["#1"])
            self.result_table.setRowCount(1)
            item = QTableWidgetItem("⚠ 0 件 / 該当データなし (SQLは正常完了)")
            item.setForeground(QColor("#e0a96b"))
            f = item.font(); f.setBold(True); item.setFont(f)
            self.result_table.setItem(0, 0, item)
            self.result_table.resizeColumnsToContents()
            return

        header = rows[0]
        body = rows[1:]
        n_fields = len(header)

        if not body:
            # ヘッダーのみ (データ無し)
            self.result_table.setRowCount(n_fields)
            self.result_table.setColumnCount(1)
            self.result_table.setVerticalHeaderLabels(
                [(h or '').strip() or f"col{i+1}" for i, h in enumerate(header)]
            )
            self.result_table.setHorizontalHeaderLabels(["#1"])
            for i in range(n_fields):
                ph = QTableWidgetItem("⚠ 0 件 / 該当データなし")
                ph.setForeground(QColor("#e0a96b"))
                f = ph.font(); f.setBold(True); ph.setFont(f)
                self.result_table.setItem(i, 0, ph)
            self.result_table.resizeColumnsToContents()
            return

        idx = min(self._current_record, len(body) - 1)
        record = body[idx]

        # 全件(縦・転置) と同じ構造: 縦ヘッダー=列名 / 横ヘッダー=#N / 1列のみ
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
        # 値列が広すぎる時は 600px に
        if self.result_table.columnWidth(0) > 600:
            self.result_table.setColumnWidth(0, 600)


# ---------------------------------------------------------------------------
# SQL 抽出・整形ダイアログ
# ---------------------------------------------------------------------------

class SqlExtractDialog(QDialog):
    open_sql_requested = pyqtSignal(str, str)  # content, filename

    def __init__(self, log_content: str, source_name: str = '', parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"SQL抽出・整形 — {source_name}")
        self.setMinimumSize(1000, 650)
        self.resize(1200, 720)
        # タイトルバーに 最小化/最大化 ボタンを表示する
        self.setWindowFlags(
            self.windowFlags()
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
        )
        self._log_content = log_content
        self._extracted: list[dict] = []
        # フィルタ後のインデックスリスト (sql_list の row → self._extracted の idx)
        self._filtered_indices: list[int] = []
        self._build_ui()
        self._extract()
        # sqlparse 未インストール時は警告
        if not _check_sqlparse():
            QMessageBox.information(
                self, "sqlparse 未インストール",
                "SQL整形ライブラリ sqlparse がインストールされていません。\n"
                "「再整形」を押しても元のSQLがそのまま表示されます。\n\n"
                "整形を有効化するには:\n"
                "    pip install sqlparse\n"
                "を実行してアプリを再起動してください。"
            )

    def _build_ui(self):
        main = QVBoxLayout()
        main.setSpacing(3)
        main.setContentsMargins(6, 6, 6, 6)

        # ─── オプションバー ───────────────────────────────────────────
        # ─── 1行目: 抽出パラメータ + 再抽出ボタン + 件数 ───
        row1 = QHBoxLayout()
        row1.setSpacing(6)
        row1.addWidget(QLabel("📋 追加プレフィックス:"))
        self.prefix_input = QLineEdit()
        self.prefix_input.setPlaceholderText("例: MyPrefix:, Exec:  (カンマ区切り)")
        self.prefix_input.setToolTip(
            "SQL検出時に剥がす独自プレフィックスを追加 (デフォルト: Hibernate:/SQL:/Execute 等)"
        )
        row1.addWidget(self.prefix_input, 1)

        row1.addSpacing(8)

        extract_btn = QPushButton("🔄 再抽出")
        extract_btn.setToolTip("プレフィックスを更新して全件抽出をやり直す")
        extract_btn.clicked.connect(self._extract)
        row1.addWidget(extract_btn)

        self.count_label = QLabel("0 件")
        self.count_label.setStyleSheet("color:#808080;font-weight:600;padding:0 4px;")
        self.count_label.setMinimumWidth(50)
        row1.addWidget(self.count_label)
        main.addLayout(row1, 0)

        # ─── 2行目: 整形オプション (キーワードケース / インデント / パラメータ置換) ───
        row2 = QHBoxLayout()
        row2.setSpacing(6)
        row2.addWidget(QLabel("整形:"))

        row2.addWidget(QLabel("キーワード"))
        self.kw_combo = QComboBox()
        self.kw_combo.addItems(["upper", "lower", "capitalize"])
        self.kw_combo.setToolTip(
            "SQLキーワード (SELECT/FROM等) の大小文字統一:\n"
            "upper: SELECT FROM\nlower: select from\ncapitalize: Select From"
        )
        self.kw_combo.setFixedWidth(110)
        row2.addWidget(self.kw_combo)

        row2.addSpacing(8)
        row2.addWidget(QLabel("インデント"))
        # 検索バーの ▲▼ と同じ操作感: 数値欄(矢印なし) + ▲▼ ボタン
        self.indent_spin = QSpinBox()
        self.indent_spin.setRange(2, 8)
        self.indent_spin.setValue(4)
        self.indent_spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.indent_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.indent_spin.setFixedWidth(34)
        self.indent_spin.setToolTip("インデントのスペース数 (2〜8)")
        row2.addWidget(self.indent_spin)
        _ind_up = QPushButton("▲")
        _ind_up.setFixedWidth(24)
        _ind_up.setToolTip("インデントを増やす")
        _ind_up.clicked.connect(lambda: self.indent_spin.stepBy(1))
        _ind_down = QPushButton("▼")
        _ind_down.setFixedWidth(24)
        _ind_down.setToolTip("インデントを減らす")
        _ind_down.clicked.connect(lambda: self.indent_spin.stepBy(-1))
        row2.addWidget(_ind_up)
        row2.addWidget(_ind_down)

        row2.addSpacing(12)
        self.subst_check = QCheckBox("パラメータ置換")
        self.subst_check.setToolTip(
            "Hibernate/MyBatisログの ? プレースホルダーをバインド値で置換する\n"
            "(値直埋め込み形式のログでは効果なし)"
        )
        self.subst_check.setChecked(True)
        row2.addWidget(self.subst_check)

        row2.addSpacing(12)
        self.insert_pairs_check = QCheckBox("INSERTを列=値で表示")
        self.insert_pairs_check.setToolTip(
            "ON: INSERT文を「列名 = 値」の対応表で表示 (確認しやすい)\n"
            "OFF: 通常のSQL文として表示 (コピーして実行したい時はこちら)"
        )
        self.insert_pairs_check.setChecked(True)
        self.insert_pairs_check.toggled.connect(self._reformat)
        row2.addWidget(self.insert_pairs_check)

        row2.addStretch()
        main.addLayout(row2, 0)

        # ─── メインスプリッター：左=リスト / 右=プレビュー ───────────
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # 左：抽出リスト
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 2, 0)
        ll.setSpacing(2)
        ll.addWidget(QLabel("抽出されたSQL:"))

        # 絞り込みフィルタ (キーワード + 種別)
        filter_row = QHBoxLayout()
        filter_row.setSpacing(4)
        filter_row.addWidget(QLabel("🔍"))
        self.list_filter_input = QLineEdit()
        self.list_filter_input.setPlaceholderText("SQLをキーワード絞り込み (例: M_WP_COLLECT_TYPE)")
        self.list_filter_input.textChanged.connect(self._on_list_filter_changed)
        filter_row.addWidget(self.list_filter_input, 1)
        self.list_kind_combo = QComboBox()
        self.list_kind_combo.addItem("全種別", "")
        self.list_kind_combo.addItem("SELECT", "SELECT")
        self.list_kind_combo.addItem("INSERT", "INSERT")
        self.list_kind_combo.addItem("UPDATE", "UPDATE")
        self.list_kind_combo.addItem("DELETE", "DELETE")
        self.list_kind_combo.setToolTip("SQL種別で絞り込み")
        self.list_kind_combo.currentIndexChanged.connect(self._on_list_filter_changed)
        filter_row.addWidget(self.list_kind_combo)
        ll.addLayout(filter_row)

        # 絞り込み件数表示 (リストヘッダー右に薄く)
        self.filter_count_label = QLabel("")
        self.filter_count_label.setStyleSheet("color:#9ED969; font-size:10px; padding:1px 4px;")
        ll.addWidget(self.filter_count_label)

        self.sql_list = QListWidget()
        self.sql_list.setAlternatingRowColors(True)
        self.sql_list.setUniformItemSizes(True)
        self.sql_list.currentRowChanged.connect(self._on_row_changed)
        ll.addWidget(self.sql_list)

        btn_row = QHBoxLayout()
        open_one_btn = QPushButton("タブで開く")
        open_one_btn.clicked.connect(self._open_one)
        copy_btn = QPushButton("コピー")
        copy_btn.clicked.connect(self._copy)
        btn_row.addWidget(open_one_btn)
        btn_row.addWidget(copy_btn)
        ll.addLayout(btn_row)
        splitter.addWidget(left)

        # 右：プレビュー（エディタ風）
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(2, 0, 0, 0)
        rl.setSpacing(2)

        preview_header = QHBoxLayout()
        preview_header.addWidget(QLabel("整形プレビュー（編集可能）:"))
        preview_header.addStretch()
        self.lineno_label = QLabel("")
        self.lineno_label.setStyleSheet("color: #606060;")
        preview_header.addWidget(self.lineno_label)
        fmt_btn = QPushButton("再整形")
        fmt_btn.clicked.connect(self._reformat)
        preview_header.addWidget(fmt_btn)
        open_all_btn = QPushButton("全件を1タブで開く")
        open_all_btn.clicked.connect(self._open_all)
        preview_header.addWidget(open_all_btn)
        # DB実行 (SSH 経由で sqlplus 等を実行して結果取得)
        db_exec_btn = QPushButton("▶ DB実行")
        db_exec_btn.setToolTip(
            "現在プレビュー中のSQLをSSH経由でDBに投げて結果を取得します\n"
            "(接続プロファイル + DB実行コマンドテンプレートが必要)"
        )
        db_exec_btn.setStyleSheet(
            "QPushButton { background:#3a6e3a; color:#e0f0e0; padding:2px 10px; }"
            "QPushButton:hover { background:#4a8e4a; }"
        )
        db_exec_btn.clicked.connect(self._open_db_execute)
        preview_header.addWidget(db_exec_btn)

        # 📤 SoraDB (別プロセス) でSQL実行: 長時間クエリ中も Sora が固まらない、
        # 並列に複数 SQL を確認したい場合に有効
        soradb_btn = QPushButton("📤 SoraDB で実行")
        soradb_btn.setToolTip(
            "現在プレビュー中のSQLを別アプリ Sora DB で実行します\n"
            "(別プロセスのため、 Sora は固まらず、 複数 SQL を並列に確認可)"
        )
        soradb_btn.setStyleSheet(
            "QPushButton { background:#3a4a6e; color:#e0e6f0; padding:2px 10px; }"
            "QPushButton:hover { background:#4a5a8e; }"
        )
        soradb_btn.clicked.connect(self._open_in_sora_db)
        preview_header.addWidget(soradb_btn)
        rl.addLayout(preview_header)

        self.preview = QPlainTextEdit()
        self.preview.setFont(QFont("Consolas", 10))
        t = _theme()
        self.preview.setStyleSheet(
            f"background:{t['editor_bg']}; color:{t['text']}; border:none; "
            f"selection-background-color:{t['selection']};"
        )
        # SQL シンタックスハイライト (LogViewer と同じ配色)
        self.preview_highlighter = SyntaxHighlighter(self.preview.document(), 'sql')
        rl.addWidget(self.preview)

        # パラメータ情報ラベル
        self.param_label = QLabel("")
        self.param_label.setStyleSheet("color: #6A8759; font-size: 10px; padding: 2px;")
        self.param_label.setWordWrap(True)
        rl.addWidget(self.param_label)
        splitter.addWidget(right)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        main.addWidget(splitter, 1)   # stretch=1 で残り領域を埋める

        # ─── 下部ボタン ────────────────────────────────────────────────
        bottom = QHBoxLayout()
        close_btn = QPushButton("閉じる")
        close_btn.clicked.connect(self.close)
        bottom.addStretch()
        bottom.addWidget(close_btn)
        main.addLayout(bottom, 0)

        self.setLayout(main)
        t = _theme()
        self.setStyleSheet(f"""
            QDialog {{ background: {t['bg']}; }}
            QLabel  {{ color: {t['text']}; }}
            QPushButton {{ background:{t['control_bg']}; color:{t['text']}; border:none; padding:2px 8px; border-radius:2px; }}
            QPushButton:hover {{ background:{t['control_hover']}; }}
            QListWidget {{ background:{t['panel_bg']}; color:{t['text']}; border:none;
                          alternate-background-color:{t['control_bg']}; font-family:Consolas, monospace; font-size:12px; }}
            QListWidget::item {{ padding:4px 6px; border-bottom:1px solid {t['border']}; }}
            QListWidget::item:selected {{ background:{t['selection']}; color:{t['text']}; }}
            QListWidget::item:hover {{ background:{t['control_hover']}; }}
            QLineEdit {{ background:{t['panel_bg']}; color:{t['text']}; border:1px solid {t['border']}; padding:1px 3px; }}
            QComboBox {{ background:{t['control_bg']}; color:{t['text']}; border:1px solid {t['border']}; padding:1px 3px; }}
            QComboBox QAbstractItemView {{ background:{t['panel_bg']}; color:{t['text']}; selection-background-color:{t['selection']}; }}
            QSpinBox  {{ background:{t['control_bg']}; color:{t['text']}; border:1px solid {t['border']};
                        padding:1px 3px; min-height:22px; min-width:54px; }}
            QCheckBox {{ color:{t['text']}; spacing:6px; }}
            QSplitter::handle {{ background:{t['border']}; width:4px; }}
        """)

    # ─── 抽出・整形ロジック ────────────────────────────────────────────

    def _extract(self):
        extras = [p.strip() for p in self.prefix_input.text().split(',') if p.strip()]
        self._extracted = _extract_sql_from_log(self._log_content, extras)
        self.count_label.setText(f"{len(self._extracted)} 件")
        self._update_list()

    def _sql_kind(self, sql: str) -> str:
        """SQL の先頭キーワードを 'SELECT'/'INSERT'/'UPDATE'/'DELETE'/'' で返す。"""
        m = re.match(r'\s*(SELECT|WITH|INSERT|MERGE|UPDATE|DELETE)\b',
                     sql, re.IGNORECASE)
        if not m:
            return ''
        kw = m.group(1).upper()
        if kw == 'WITH':
            return 'SELECT'
        if kw == 'MERGE':
            return 'INSERT'
        return kw

    def _on_list_filter_changed(self, *_):
        """検索キーワード or 種別変更時の絞り込み再描画。"""
        self._update_list()

    def _update_list(self):
        self.sql_list.blockSignals(True)
        self.sql_list.clear()

        # フィルタ条件取得
        keyword = ''
        kind_filter = ''
        if hasattr(self, 'list_filter_input'):
            keyword = self.list_filter_input.text().strip().lower()
        if hasattr(self, 'list_kind_combo'):
            kind_filter = self.list_kind_combo.currentData() or ''

        # 絞り込み: self._extracted → self._filtered_indices
        self._filtered_indices = []
        for i, entry in enumerate(self._extracted):
            sql_text = entry['sql']
            if kind_filter and self._sql_kind(sql_text) != kind_filter:
                continue
            if keyword and keyword not in sql_text.lower():
                continue
            self._filtered_indices.append(i)

        # 絞り込み件数表示
        if hasattr(self, 'filter_count_label'):
            total = len(self._extracted)
            shown = len(self._filtered_indices)
            if shown == total:
                self.filter_count_label.setText(f"{total} 件")
            else:
                self.filter_count_label.setText(f"{shown} / {total} 件 (絞り込み中)")

        # リスト描画 (視認性の高い明るい配色)
        for i in self._filtered_indices:
            entry = self._extracted[i]
            preview = entry['sql'][:70].replace('\n', ' ')
            if len(entry['sql']) > 70:
                preview += '…'
            has_params = bool(entry['params'])
            marker = ' [?]' if '?' in entry['sql'] and has_params else ''
            sql_kind = ''
            # 種別色はテーマ明暗で切替 (ライト背景・選択青背景でも読めるように)
            _light = _is_light_theme()
            color = QColor("#333333" if _light else "#e0e0e0")
            if re.match(r'\s*(SELECT|WITH)\b', entry['sql'], re.IGNORECASE):
                sql_kind = 'SEL'
                color = QColor("#2E7D32" if _light else "#9ED969")
            elif re.match(r'\s*(INSERT|MERGE)\b', entry['sql'], re.IGNORECASE):
                sql_kind = 'INS'
                color = QColor("#1565C0" if _light else "#82AAFF")
            elif re.match(r'\s*(UPDATE)\b', entry['sql'], re.IGNORECASE):
                sql_kind = 'UPD'
                color = QColor("#B05A00" if _light else "#FFB454")
            elif re.match(r'\s*(DELETE)\b', entry['sql'], re.IGNORECASE):
                sql_kind = 'DEL'
                color = QColor("#C0392B" if _light else "#FF6E6E")
            kind_label = f"[{sql_kind}]" if sql_kind else "[?  ]"
            # 元の連番 i+1 を保持して表示 (絞り込み後も元の番号が分かる)
            item = QListWidgetItem(f" {i+1:>3}. {kind_label}{marker}  {preview}")
            item.setToolTip(f"ログ行 {entry['lineno']}\n{entry['sql'][:300]}")
            item.setForeground(color)
            f = item.font()
            f.setPointSize(max(10, f.pointSize()))
            item.setFont(f)
            self.sql_list.addItem(item)
        self.sql_list.blockSignals(False)
        if self._filtered_indices:
            self.sql_list.setCurrentRow(0)
        else:
            # マッチ無し → プレビューと情報をクリア
            self.preview.clear()
            self.lineno_label.setText("")
            self.param_label.setText("")

    def _on_row_changed(self, row):
        # row は sql_list の表示インデックス。実 entry は filtered_indices 経由
        if not (0 <= row < len(self._filtered_indices)):
            return
        real_idx = self._filtered_indices[row]
        if 0 <= real_idx < len(self._extracted):
            self._show_entry(self._extracted[real_idx])

    def _show_entry(self, entry: dict):
        sql = entry['sql']
        params = entry['params']

        if self.subst_check.isChecked() and params:
            sql = _substitute_params(sql, params)

        formatted = _try_format_sql(sql, self.indent_spin.value(), self.kw_combo.currentText(), self.insert_pairs_check.isChecked())
        self.preview.setPlainText(formatted)
        self.lineno_label.setText(f"ログ行: {entry['lineno']}")

        if params:
            param_txt = '  '.join(f"[{k}]={v}" for k, v in sorted(params.items()))
            self.param_label.setText(f"バインドパラメータ: {param_txt}")
        else:
            self.param_label.setText("")

    def _reformat(self):
        row = self.sql_list.currentRow()
        if 0 <= row < len(self._filtered_indices):
            self._show_entry(self._extracted[self._filtered_indices[row]])

    # ─── タブ操作 ─────────────────────────────────────────────────────

    def _open_one(self):
        text = self.preview.toPlainText().strip()
        if not text:
            return
        row = self.sql_list.currentRow()
        # 元の連番 (絞り込み前のインデックス + 1) でファイル名を作る
        if 0 <= row < len(self._filtered_indices):
            real_idx = self._filtered_indices[row]
            fname = f"query_{real_idx + 1}.sql"
        else:
            fname = f"query_{row + 1}.sql"
        self.open_sql_requested.emit(text, fname)

    def _open_all(self):
        # 絞り込み中なら絞り込み結果のみ、絞り込み無しなら全件
        targets = self._filtered_indices if self._filtered_indices else range(len(self._extracted))
        if not targets:
            return
        parts = []
        for i in targets:
            entry = self._extracted[i]
            sql = entry['sql']
            if self.subst_check.isChecked() and entry['params']:
                sql = _substitute_params(sql, entry['params'])
            formatted = _try_format_sql(sql, self.indent_spin.value(), self.kw_combo.currentText(), self.insert_pairs_check.isChecked())
            parts.append(f"-- ===== Query {i + 1}  (log line {entry['lineno']}) =====\n{formatted}")
        suffix = "_filtered" if (
            self._filtered_indices and len(self._filtered_indices) != len(self._extracted)
        ) else ""
        self.open_sql_requested.emit('\n\n'.join(parts), f"all_queries{suffix}.sql")

    def _copy(self):
        text = self.preview.toPlainText().strip()
        if text:
            QApplication.clipboard().setText(text)
            self.param_label.setText("クリップボードにコピーしました")

    # ─── DB実行ダイアログ用ナビゲーション API ────────────────────────────
    # index は「絞り込み後リスト上の位置」で扱う。これにより DB実行ダイアログの
    # ◁▷ ボタンも絞り込み結果に対して順次移動する。

    def get_sql_count(self) -> int:
        """絞り込み後の SQL 件数を返す。"""
        return len(self._filtered_indices)

    def get_current_index(self) -> int:
        """現在選択中の SQL のリスト上インデックス。未選択時は -1。"""
        return self.sql_list.currentRow()

    def get_formatted_sql_at(self, index: int) -> tuple[str, int]:
        """指定インデックス (絞り込み後) の整形済み SQL とログ行番号を返す。
        現在のオプション (kw_combo / indent_spin / subst_check) を適用する。
        範囲外の場合は ('', -1)。
        """
        if not (0 <= index < len(self._filtered_indices)):
            return ('', -1)
        real_idx = self._filtered_indices[index]
        entry = self._extracted[real_idx]
        sql = entry['sql']
        if self.subst_check.isChecked() and entry['params']:
            sql = _substitute_params(sql, entry['params'])
        formatted = _try_format_sql(sql, self.indent_spin.value(), self.kw_combo.currentText(), self.insert_pairs_check.isChecked())
        return (formatted, entry['lineno'])

    def navigate_to(self, index: int):
        """絞り込み後リストの index に選択を移動 (プレビューも追随)。"""
        if 0 <= index < len(self._filtered_indices):
            self.sql_list.setCurrentRow(index)

    def _open_db_execute(self):
        """現在プレビューしているSQLをDB実行ダイアログに渡す (モードレス)。"""
        sql = self.preview.toPlainText().strip()
        if not sql:
            QMessageBox.information(self, "SQL未選択",
                "実行するSQLが選択されていません。\n左のリストから選んで「再整形」を押してください。")
            return
        # 既にDB実行ダイアログが開いていれば、SQLだけ差し替えて前面に出す
        if getattr(self, '_db_dialog', None) is not None:
            try:
                if self._db_dialog.isVisible():
                    self._db_dialog.sql_input.setPlainText(sql)
                    self._db_dialog.raise_()
                    self._db_dialog.activateWindow()
                    return
            except Exception:
                self._db_dialog = None

        # 親 (MainWindow) から起動元プロファイル名を取得
        default_profile = ''
        parent = self.parent()
        if parent is not None and hasattr(parent, '_origin_profile'):
            default_profile = getattr(parent, '_origin_profile', '') or ''
        # navigator = self を渡すと DB実行ダイアログで ◁▷ ボタンが有効化される
        dlg = DBExecuteDialog(
            sql,
            default_profile=default_profile,
            parent=self,
            navigator=self,
        )
        dlg.setWindowModality(Qt.WindowModality.NonModal)
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        # 参照を保持 (閉じたら自動でクリア)
        self._db_dialog = dlg
        dlg.destroyed.connect(lambda _=None: setattr(self, '_db_dialog', None))
        dlg.show()

    def _open_in_sora_db(self):
        """現在プレビュー中の SQL を別プロセスの Sora DB に渡して起動する。
        Sora DB は --profile / --query 引数で初期 SQL とプロファイルを受け取る。
        EXE 配布時は兄弟フォルダ / 同階層の 'Sora DB' を探索、
        開発時は同フォルダの sora_db.py を sys.executable で起動する。"""
        sql = self.preview.toPlainText().strip()
        if not sql:
            QMessageBox.information(self, "SQL未選択",
                "実行するSQLが選択されていません。")
            return
        # 親 (MainWindow) から起動元プロファイル名を取得
        default_profile = ''
        parent = self.parent()
        if parent is not None and hasattr(parent, '_origin_profile'):
            default_profile = getattr(parent, '_origin_profile', '') or ''

        import subprocess as _sp
        try:
            if getattr(sys, 'frozen', False):
                exe_dir = os.path.dirname(sys.executable)
                parent_dir = os.path.dirname(exe_dir)
                candidates = [
                    os.path.join(exe_dir, "Sora DB.exe"),
                    os.path.join(exe_dir, "Sora DB", "Sora DB.exe"),
                    os.path.join(parent_dir, "Sora DB", "Sora DB.exe"),
                ]
                soradb_exe = next((p for p in candidates if os.path.isfile(p)), None)
                if soradb_exe is None:
                    QMessageBox.warning(
                        self, "Sora DB が見つかりません",
                        "Sora DB.exe が見つかりません。\n探した場所:\n  "
                        + "\n  ".join(candidates) + "\n\n"
                        "EXE版を使う場合は同じフォルダ (または兄弟フォルダ) に\n"
                        "Sora DB を配置してください。",
                    )
                    return
                cmd = [soradb_exe]
                cwd = os.path.dirname(soradb_exe)
            else:
                soradb_script = os.path.join(
                    os.path.dirname(os.path.abspath(__file__)), 'sora_db.py'
                )
                if not os.path.isfile(soradb_script):
                    QMessageBox.warning(self, "Sora DB が見つかりません",
                                        f"開発スクリプトが無い: {soradb_script}")
                    return
                cmd = [sys.executable, soradb_script]
                cwd = os.path.dirname(soradb_script)
            cmd += ['--query', sql]
            if default_profile:
                cmd += ['--profile', default_profile]
            _sp.Popen(cmd, cwd=cwd)
        except Exception as e:
            QMessageBox.critical(self, "起動エラー",
                                 f"Sora DB の起動に失敗しました:\n{type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# エントリーポイント
# ---------------------------------------------------------------------------

def _parse_cli_args(argv: list[str]) -> dict:
    """コマンドライン引数を共通フォーマット (dict) にパースする。
      file1 file2 ...   : 開くファイル
      --search KEYWORD  : 起動後に検索バーで自動検索
      --regex           : --search の内容を正規表現として扱う (Aa/.*  の .* を ON)
      --profile NAME    : DB実行ダイアログで初期選択する接続プロファイル
      --sql-extract     : 起動直後に SQL抽出ダイアログを自動で開く
    """
    files: list[str] = []
    search_term = ''
    use_regex = False
    profile_name = ''
    auto_sql_extract = False
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == '--search' and i + 1 < len(argv):
            search_term = argv[i + 1]; i += 2
        elif a.startswith('--search='):
            search_term = a[len('--search='):]; i += 1
        elif a == '--regex':
            use_regex = True; i += 1
        elif a == '--profile' and i + 1 < len(argv):
            profile_name = argv[i + 1]; i += 2
        elif a.startswith('--profile='):
            profile_name = a[len('--profile='):]; i += 1
        elif a == '--sql-extract':
            auto_sql_extract = True; i += 1
        elif os.path.isfile(a):
            # 絶対パスに正規化して別プロセスに渡しても解決できるように
            files.append(os.path.abspath(a)); i += 1
        else:
            i += 1
    return {
        'files': files, 'search': search_term, 'regex': use_regex,
        'profile': profile_name, 'sql_extract': auto_sql_extract,
    }


if __name__ == '__main__':
    import getpass
    from PyQt6.QtNetwork import QLocalServer, QLocalSocket

    req = _parse_cli_args(sys.argv[1:])

    # ── 単一インスタンス制御 ───────────────────────────────────────────
    # 既に Sora Editor が起動していれば、引数を渡してそちらにタブで開かせ、
    # 自分はすぐ終了する。これで何回起動しても1ウィンドウにタブが増える。
    _SINGLETON_KEY = f"SoraEditor_{getpass.getuser()}"
    _probe = QLocalSocket()
    _probe.connectToServer(_SINGLETON_KEY)
    if _probe.waitForConnected(300):
        # 既存インスタンスあり → リクエストを送信して終了
        try:
            _probe.write(json.dumps(req).encode('utf-8'))
            _probe.flush()
            _probe.waitForBytesWritten(2000)
        finally:
            _probe.disconnectFromServer()
        sys.exit(0)
    _probe.abort()

    # ── ここからプライマリ (最初の) インスタンス ────────────────────────
    # 起動時の一時ファイルクリーンアップ (FTP ダウンロード分)
    import tempfile as _tempfile
    try:
        _ftp_tmp = os.path.join(_tempfile.gettempdir(), 'text_editor_ftp')
        _cleanup_old_temp_files(_ftp_tmp)
    except Exception:
        pass

    app = QApplication(sys.argv)
    app.setApplicationName("Sora Editor")
    # Qt 標準ダイアログ (QMessageBox の Yes/No/Ok/Cancel 等) を日本語化
    try:
        from PyQt6.QtCore import QTranslator, QLibraryInfo, QLocale
        _qt_tr = QTranslator()
        _candidates = [QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)]
        # frozen (PyInstaller) では --add-data で同梱した場所もチェック
        if getattr(sys, 'frozen', False):
            base = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
            _candidates.insert(0, os.path.join(base, 'PyQt6', 'Qt6', 'translations'))
        for _p in _candidates:
            if _qt_tr.load(QLocale("ja"), "qtbase", "_", _p):
                app.installTranslator(_qt_tr)
                break
    except Exception:
        pass
    try:
        from app_icons import text_editor_icon
        app.setWindowIcon(text_editor_icon())
    except Exception:
        pass
    window = MainWindow()
    window.show()

    # ローカルサーバーを立てて後続プロセスからの open 要求を受け付ける
    _server = QLocalServer()
    QLocalServer.removeServer(_SINGLETON_KEY)   # 残骸があれば除去
    _server.listen(_SINGLETON_KEY)

    def _on_new_connection():
        sock = _server.nextPendingConnection()
        if sock is None:
            return
        if sock.waitForReadyRead(2000):
            try:
                data = bytes(sock.readAll()).decode('utf-8')
                remote_req = json.loads(data)
                window.apply_open_request(remote_req)
            except Exception:
                pass
        sock.disconnectFromServer()

    _server.newConnection.connect(_on_new_connection)

    # 自分自身の起動引数を適用
    window.apply_open_request(req)

    sys.exit(app.exec())
