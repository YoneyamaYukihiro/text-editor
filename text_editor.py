#!/usr/bin/env python3
"""Sora Editor — マルチタブ・FTP対応のテキストエディタ"""
__version__ = "1.0.0"

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
)
from PyQt6.QtCore import Qt, QRegularExpression, pyqtSignal, QSize, QThread, QTimer, QFileSystemWatcher
from PyQt6.QtGui import (
    QFont, QColor, QTextCharFormat, QSyntaxHighlighter,
    QKeySequence, QAction, QPainter, QTextFormat, QTextDocument,
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
        'line_highlight':'#3a3a3a',
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
        'line_highlight':'#1a2640',
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
        'line_highlight':'#202020',
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
        'line_highlight':'#303030',
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
        'line_highlight':'#eef2f8',
        'gutter_bg':     '#f0f0f0',
        'gutter_fg':     '#888888',
    },
    'Solarized Light': {
        'bg':            '#fdf6e3',
        'panel_bg':      '#eee8d5',
        'editor_bg':     '#fdf6e3',
        'toolbar_bg':    '#e4dcc3',
        'text':          '#586e75',
        'text_dim':      '#93a1a1',
        'selection':     '#cfd9c4',
        'border':        '#b8b298',
        'control_bg':    '#e4dcc3',
        'control_hover': '#d4cba8',
        'line_highlight':'#eee8d5',
        'gutter_bg':     '#eee8d5',
        'gutter_fg':     '#93a1a1',
    },
}

_DEFAULT_SETTINGS = {
    'editor_font_size': 11,
    'ui_font_size':     10,
    'theme':            'Dark',
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


def _theme() -> dict:
    return _THEME_PRESETS.get(SETTINGS.get('theme', 'Dark'), _THEME_PRESETS['Dark'])


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

        fs = SETTINGS.get('editor_font_size', 11)
        font = QFont("Consolas", fs)
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
        block = self.document().findBlockByLineNumber(target - 1)
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
        block = self.document().findBlockByLineNumber(target - 1)
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

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                lineno = block_number + 1

                # 変更バー
                kind = self._change_map.get(lineno)
                if kind in self._GUTTER_COLORS:
                    painter.fillRect(0, top, gw, line_h, self._GUTTER_COLORS[kind])

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

                # 行番号
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
        extra = list(self._search_selections)

        # 変更行の薄い背景着色 (added/modified/deleted)
        if self._change_map:
            doc = self.document()
            for lineno, kind in self._change_map.items():
                color = self._LINE_BG_COLORS.get(kind)
                if not color:
                    continue
                block = doc.findBlockByLineNumber(lineno - 1)
                if not block.isValid():
                    continue
                sel = QTextEdit.ExtraSelection()
                sel.format.setBackground(color)
                sel.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
                cur = self.textCursor()
                cur.setPosition(block.position())
                sel.cursor = cur
                extra.append(sel)

        # 現在行ハイライト
        if not self.isReadOnly():
            sel = QTextEdit.ExtraSelection()
            sel.format.setBackground(QColor(_theme()['line_highlight']))
            sel.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
            sel.cursor = self.textCursor()
            sel.cursor.clearSelection()
            extra.append(sel)
        self.setExtraSelections(extra)


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
            'line_levels': [
                (r'\b(?:ERROR|CRITICAL|FATAL|SEVERE)\b',  '#3D1515', '#FF7070'),
                (r'\b(?:WARN(?:ING)?)\b',                 '#2D2512', '#E8B26A'),
                (r'\b(?:INFO|INFORMATION)\b',             '#1A2D1A', '#6A9F6A'),
                (r'\b(?:DEBUG)\b',                        None,      '#707070'),
                (r'\b(?:TRACE|VERBOSE)\b',                None,      '#555555'),
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
        self._comment_fmt = self._fmt('#808080', italic=True)
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

        # --- 通常言語ルール ---
        # 注: 後から append したルールが先のルールを上書きするため、
        #     優先度の低いもの (数値) から順に追加し、文字列・コメントを最後に置く。
        # キーワード（橙・太字）
        kw_fmt = self._fmt('#CC7832', bold=True)
        for kw in spec.get('keywords', []):
            pat = QRegularExpression(r'\b' + kw + r'\b', re_opts)
            self._rules.append((pat, kw_fmt))

        # データ型（水色）
        type_fmt = self._fmt('#4EC9B0', bold=True)
        for t in spec.get('types', []):
            pat = QRegularExpression(r'\b' + t + r'\b', re_opts)
            self._rules.append((pat, type_fmt))

        # 組み込み関数（黄緑）
        fn_fmt = self._fmt('#DCDCAA')
        for fn in spec.get('functions', []):
            pat = QRegularExpression(r'\b' + fn + r'\b', re_opts)
            self._rules.append((pat, fn_fmt))

        # 数値（青）— ※先に追加して、後段の文字列ルールで上書きされるようにする
        # （文字列リテラル内 '#2b2b2b' の数字に青色が乗らないため）
        if 'line_levels' not in spec:
            self._rules.append((QRegularExpression(r'\b\d+\.?\d*\b'), self._fmt('#6897BB')))

        # 文字列リテラル（緑）— 数値より後に追加 → 文字列が数値を上書き
        str_fmt = self._fmt('#6A8759')
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
        kw_fmt = self._fmt('#CC7832', bold=True)
        for m in self._SQL_KEYWORDS_RE.finditer(text):
            self.setFormat(m.start(), m.end() - m.start(), kw_fmt)
        num_fmt = self._fmt('#6897BB')
        for m in self._SQL_NUMBER_RE.finditer(text):
            self.setFormat(m.start(), m.end() - m.start(), num_fmt)
        str_fmt = self._fmt('#6A8759')
        for m in self._SQL_STRING_RE.finditer(text):
            self.setFormat(m.start(), m.end() - m.start(), str_fmt)
        cm_fmt = self._fmt('#808080', italic=True)
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


# ---------------------------------------------------------------------------
# インライン検索バー（エディタ下部に埋め込み）
# ---------------------------------------------------------------------------

class InlineSearchBar(QWidget):
    _MAX_HISTORY = 20

    def __init__(self, editor: 'CodeEditor', parent=None):
        super().__init__(parent)
        self._editor = editor
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
        layout.setContentsMargins(6, 2, 6, 2)
        layout.setSpacing(4)

        # --- 検索欄（履歴コンボ） ---
        self.search_input = QComboBox()
        self.search_input.setEditable(True)
        self.search_input.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.search_input.lineEdit().setPlaceholderText("検索... (Enter: 次へ / Shift+Enter: 前へ)")
        self.search_input.setMinimumWidth(200)
        self.search_input.setMaximumWidth(280)
        self.search_input.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        layout.addWidget(self.search_input)

        # 履歴ドロップダウンを確実に開くためのボタン
        search_hist_btn = QPushButton("📜")
        search_hist_btn.setFixedWidth(24)
        search_hist_btn.setToolTip("検索履歴を開く")
        search_hist_btn.clicked.connect(self.search_input.showPopup)
        layout.addWidget(search_hist_btn)

        self.prev_btn = QPushButton("▲")
        self.prev_btn.setFixedWidth(26)
        self.prev_btn.setToolTip("前を検索 (Shift+Enter)")
        self.next_btn = QPushButton("▼")
        self.next_btn.setFixedWidth(26)
        self.next_btn.setToolTip("次を検索 (Enter)")
        layout.addWidget(self.prev_btn)
        layout.addWidget(self.next_btn)

        self.match_label = QLabel("")
        self.match_label.setFixedWidth(72)
        self.match_label.setStyleSheet("color:#808080; font-size:10px;")
        layout.addWidget(self.match_label)

        layout.addWidget(self._sep())

        # --- 置換欄（履歴コンボ） ---
        self.replace_input = QComboBox()
        self.replace_input.setEditable(True)
        self.replace_input.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.replace_input.lineEdit().setPlaceholderText("置換後のテキスト")
        self.replace_input.setMinimumWidth(160)
        self.replace_input.setMaximumWidth(220)
        self.replace_input.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        layout.addWidget(self.replace_input)

        replace_hist_btn = QPushButton("📜")
        replace_hist_btn.setFixedWidth(24)
        replace_hist_btn.setToolTip("置換履歴を開く")
        replace_hist_btn.clicked.connect(self.replace_input.showPopup)
        layout.addWidget(replace_hist_btn)

        self.replace_btn = QPushButton("置換")
        self.replace_btn.setFixedWidth(44)
        self.replace_all_btn = QPushButton("全置換")
        self.replace_all_btn.setFixedWidth(52)
        layout.addWidget(self.replace_btn)
        layout.addWidget(self.replace_all_btn)

        layout.addWidget(self._sep())

        # --- オプション ---
        self.case_check = QCheckBox("Aa")
        self.case_check.setToolTip("大文字小文字を区別する")
        self.regex_check = QCheckBox(".*")
        self.regex_check.setToolTip("正規表現")
        layout.addWidget(self.case_check)
        layout.addWidget(self.regex_check)

        layout.addStretch()

        close_btn = QPushButton("✕")
        close_btn.setFixedWidth(24)
        layout.addWidget(close_btn)

        self.setLayout(layout)
        # ※ QComboBox の矢印描画は環境差が大きいため CSS をシンプルに留め、
        #    別途「📜」アイコンの専用「履歴」ボタンを後ろに置いて確実に開けるようにする。
        self.setStyleSheet("""
            QWidget   { background: #333333; }
            QLabel    { color: #a9b7c6; }
            QComboBox { background:#3a3a3a; color:#a9b7c6; border:1px solid #555;
                        padding:1px 3px; }
            QComboBox QAbstractItemView { background:#2b2b2b; color:#a9b7c6;
                                          selection-background-color:#214283; }
        """)
        self.setMaximumHeight(32)

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
        close_btn.clicked.connect(self.close_bar)

    def _on_input_changed(self, text):
        """入力中はタイマー再起動。ドキュメントサイズに応じて遅延を調整。"""
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

    def show_bar(self, initial_text: str = None):
        """初期テキスト指定可。指定があれば検索欄に挿入してハイライト即実行。"""
        self.show()
        if initial_text:
            self.search_input.setCurrentText(initial_text)
        self.search_input.lineEdit().setFocus()
        self.search_input.lineEdit().selectAll()
        self._update_highlights()

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

        doc_text = self._editor.document().toPlainText()

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
        flags = self._find_flags()
        if backward:
            flags |= QTextDocument.FindFlag.FindBackward

        if self.regex_check.isChecked():
            pat = QRegularExpression(text)
            if not self.case_check.isChecked():
                pat.setPatternOptions(QRegularExpression.PatternOption.CaseInsensitiveOption)
            found = self._editor.find(pat, flags)
            if not found:
                cur = self._editor.textCursor()
                cur.movePosition(cur.MoveOperation.End if backward else cur.MoveOperation.Start)
                self._editor.setTextCursor(cur)
                self._editor.find(pat, flags)
        else:
            found = self._editor.find(text, flags)
            if not found:
                cur = self._editor.textCursor()
                cur.movePosition(cur.MoveOperation.End if backward else cur.MoveOperation.Start)
                self._editor.setTextCursor(cur)
                self._editor.find(text, flags)

    def find_next(self):
        self._push_history(self.search_input, self._search_text())
        self._do_find(backward=False)

    def find_prev(self):
        self._push_history(self.search_input, self._search_text())
        self._do_find(backward=True)

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
        self.delete_btn = QPushButton("削除")
        profile_row.addWidget(self.save_btn)
        profile_row.addWidget(self.delete_btn)
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
        cancel = QPushButton("キャンセル")
        btns.addWidget(ok)
        btns.addWidget(cancel)
        layout.addLayout(btns)
        self.setLayout(layout)

        # シグナル
        self.profile_combo.currentIndexChanged.connect(self._on_profile_selected)
        self.save_btn.clicked.connect(self._save_profile)
        self.delete_btn.clicked.connect(self._delete_profile)
        ok.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)

        self._update_delete_btn()

    # --- プロファイル操作 ---

    def _on_profile_selected(self, idx):
        if idx == 0:
            self._update_delete_btn()
            return
        name = self.profile_combo.currentText()
        p = self._profiles.get(name, {})
        self.host.setText(p.get('host', ''))
        self.port.setText(str(p.get('port', 21)))
        self.user.setText(p.get('user', 'anonymous'))
        self.password.setText(p.get('password', ''))
        self._update_delete_btn()

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
        self._update_delete_btn()

    def _delete_profile(self):
        name = self.profile_combo.currentText()
        if name == '-- 新規 --':
            return
        ans = QMessageBox.question(
            self, "削除確認", f"「{name}」を削除しますか？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        self._profiles.pop(name, None)
        save_profiles(self._profiles)
        self.profile_combo.blockSignals(True)
        self.profile_combo.removeItem(self.profile_combo.currentIndex())
        self.profile_combo.setCurrentIndex(0)
        self.profile_combo.blockSignals(False)
        self._update_delete_btn()

    def _update_delete_btn(self):
        self.delete_btn.setEnabled(self.profile_combo.currentIndex() > 0)

    def info(self):
        return {
            'host': self.host.text(),
            'port': int(self.port.text() or 21),
            'user': self.user.text(),
            'password': self.password.text(),
        }


# ---------------------------------------------------------------------------
# FTPパネル
# ---------------------------------------------------------------------------

class FTPPanel(QWidget):
    file_downloaded      = pyqtSignal(str, str)  # content, filename (互換用)
    file_downloaded_path = pyqtSignal(str, str)  # local_path, filename (新規)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.ftp = None
        self.current_path = '/'
        # ローカルパスを渡して「未保存編集あり」かを返すコールバック (MainWindow が注入)
        self._is_modified_cb = lambda _local_path: False

    def set_modification_checker(self, fn):
        """MainWindow から呼ぶ: 引数local_path → bool (未保存編集あり) を返す関数"""
        self._is_modified_cb = fn

        layout = QVBoxLayout()
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)

        self.status_label = QLabel("未接続")
        self.status_label.setStyleSheet("color: #808080; padding: 2px;")
        layout.addWidget(self.status_label)

        btns = QHBoxLayout()
        self.connect_btn = QPushButton("接続")
        self.disconnect_btn = QPushButton("切断")
        self.disconnect_btn.setEnabled(False)
        btns.addWidget(self.connect_btn)
        btns.addWidget(self.disconnect_btn)
        layout.addLayout(btns)

        self.path_label = QLabel("/")
        self.path_label.setStyleSheet("padding: 3px; background: #3a3a3a; color: #a9b7c6;")
        layout.addWidget(self.path_label)

        self.file_list = QListWidget()
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
            self.status_label.setText(f"接続中: {info['host']}")
            self.status_label.setStyleSheet("color: #6A8759; padding: 2px;")
            self.connect_btn.setEnabled(False)
            self.disconnect_btn.setEnabled(True)
            self._list('/')
        except Exception as e:
            QMessageBox.critical(self, "接続エラー", str(e))

    def _disconnect(self):
        if self.ftp:
            try:
                self.ftp.quit()
            except Exception:
                pass
            self.ftp = None
        self.status_label.setText("未接続")
        self.status_label.setStyleSheet("color: #808080; padding: 2px;")
        self.connect_btn.setEnabled(True)
        self.disconnect_btn.setEnabled(False)
        self.file_list.clear()
        self.open_btn.setEnabled(False)

    def _list(self, path):
        if not self.ftp:
            return
        try:
            self.ftp.cwd(path)
            self.current_path = self.ftp.pwd()
            self.path_label.setText(self.current_path)
            self.file_list.clear()

            if self.current_path != '/':
                item = QListWidgetItem("[..] 親フォルダへ")
                item.setData(Qt.ItemDataRole.UserRole, ('dir', '..'))
                item.setForeground(QColor("#6897BB"))
                self.file_list.addItem(item)

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
                else:
                    item = QListWidgetItem(f"📄 {name}")
                    item.setData(Qt.ItemDataRole.UserRole, ('file', name))
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
        items = self.file_list.selectedItems()
        ok = bool(items and items[0].data(Qt.ItemDataRole.UserRole)
                  and items[0].data(Qt.ItemDataRole.UserRole)[0] == 'file')
        self.open_btn.setEnabled(ok)

    def _open_selected(self):
        items = self.file_list.selectedItems()
        if items:
            data = items[0].data(Qt.ItemDataRole.UserRole)
            if data and data[0] == 'file':
                self._download(data[1])

    # サイズ閾値
    _SIZE_WARN = 5 * 1024 * 1024       # 5 MB
    _SIZE_HARD = 100 * 1024 * 1024     # 100 MB

    def _download(self, name):
        if not self.ftp:
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

        try:
            with open(local_path, 'wb') as f:
                self.ftp.retrbinary(f'RETR {name}', f.write)
        except Exception as e:
            QMessageBox.warning(self, "ダウンロードエラー", str(e))
            return

        # 4. ローカルパスでファイルを開く (`_load_file` 経由 → Ctrl+S で上書き可)
        self.file_downloaded_path.emit(local_path, name)


# ---------------------------------------------------------------------------
# ブックマークパネル
# ---------------------------------------------------------------------------

class BookmarkPanel(QWidget):
    jump_requested = pyqtSignal(object, int)  # EditorTab, lineno

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tab_refs: list[tuple[str, object]] = []  # (label, EditorTab)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)

        header = QHBoxLayout()
        header.addWidget(QLabel("ブックマーク一覧"))
        refresh_btn = QPushButton("更新")
        refresh_btn.setMaximumWidth(50)
        refresh_btn.clicked.connect(self._refresh)
        clear_btn = QPushButton("全削除")
        clear_btn.setMaximumWidth(60)
        clear_btn.clicked.connect(self._clear_all)
        header.addStretch()
        header.addWidget(refresh_btn)
        header.addWidget(clear_btn)
        layout.addLayout(header)

        self.list_widget = QListWidget()
        self.list_widget.itemDoubleClicked.connect(self._on_double_click)
        layout.addWidget(self.list_widget)

        hint = QLabel("ダブルクリックでジャンプ  /  F2：マーク切替  /  F3：次へ  /  Shift+F3：前へ")
        hint.setStyleSheet("color: #606060; font-size: 10px;")
        layout.addWidget(hint)
        self.setLayout(layout)

    def set_tabs(self, tab_refs: list[tuple[str, object]]):
        self._tab_refs = tab_refs
        self._refresh()

    def _refresh(self):
        self.list_widget.clear()
        for label, tab in self._tab_refs:
            editor = tab.editor
            for lineno in sorted(editor._bookmarks):
                block = editor.document().findBlockByLineNumber(lineno - 1)
                preview = block.text().strip()[:60] if block.isValid() else ''
                item = QListWidgetItem(f"  行 {lineno:>5}   {preview}")
                item.setData(Qt.ItemDataRole.UserRole, (tab, lineno))
                item.setToolTip(f"{label}  行 {lineno}")
                # エラー行は赤っぽく
                if re.search(r'\b(?:ERROR|CRITICAL|FATAL)\b', preview, re.IGNORECASE):
                    item.setForeground(QColor("#FF7070"))
                elif re.search(r'\bWARN', preview, re.IGNORECASE):
                    item.setForeground(QColor("#E8B26A"))
                else:
                    item.setForeground(QColor("#4A9EFF"))

                # ファイル名ヘッダーを初回だけ挿入
                if not self.list_widget.count() or \
                        self.list_widget.item(self.list_widget.count() - 1).data(
                            Qt.ItemDataRole.UserRole + 1) != label:
                    header_item = QListWidgetItem(f"📄 {label}")
                    header_item.setFlags(Qt.ItemFlag.NoItemFlags)
                    header_item.setForeground(QColor("#6897BB"))
                    header_item.setData(Qt.ItemDataRole.UserRole + 1, label)
                    self.list_widget.addItem(header_item)
                    item.setData(Qt.ItemDataRole.UserRole + 1, label)

                self.list_widget.addItem(item)

    def _on_double_click(self, item):
        data = item.data(Qt.ItemDataRole.UserRole)
        if data:
            self.jump_requested.emit(data[0], data[1])

    def _clear_all(self):
        for _label, tab in self._tab_refs:
            tab.editor._bookmarks.clear()
            tab.editor.line_number_area.update()
        self._refresh()


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
                try:
                    with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
                        for lineno, line in enumerate(f, 1):
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

class GrepPanel(QWidget):
    open_file_requested = pyqtSignal(str, int)  # filepath, lineno

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        self._file_items = {}
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)

        # 1行目：パターン + ファイルフィルタ
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("検索:"))
        self.pattern_input = QLineEdit()
        self.pattern_input.setPlaceholderText("検索パターン")
        row1.addWidget(self.pattern_input, 2)
        row1.addWidget(QLabel("ファイル:"))
        self.glob_input = QLineEdit("*")
        self.glob_input.setMaximumWidth(130)
        self.glob_input.setPlaceholderText("*.py, *.txt")
        row1.addWidget(self.glob_input)
        layout.addLayout(row1)

        # 2行目：フォルダ選択
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("フォルダ:"))
        self.dir_input = QLineEdit()
        self.dir_input.setPlaceholderText("検索するフォルダを選択...")
        row2.addWidget(self.dir_input, 1)
        self.browse_btn = QPushButton("...")
        self.browse_btn.setMaximumWidth(32)
        row2.addWidget(self.browse_btn)
        layout.addLayout(row2)

        # 3行目：オプション + 実行ボタン
        row3 = QHBoxLayout()
        self.case_check = QCheckBox("大文字小文字区別")
        self.regex_check = QCheckBox("正規表現")
        self.search_btn = QPushButton("検索")
        self.stop_btn = QPushButton("停止")
        self.stop_btn.setEnabled(False)
        self.result_label = QLabel("")
        row3.addWidget(self.case_check)
        row3.addWidget(self.regex_check)
        row3.addWidget(self.search_btn)
        row3.addWidget(self.stop_btn)
        row3.addStretch()
        row3.addWidget(self.result_label)
        layout.addLayout(row3)

        # 結果ツリー
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["ファイル / 行番号", "マッチ内容"])
        self.tree.setColumnWidth(0, 280)
        self.tree.setRootIsDecorated(True)
        self.tree.itemDoubleClicked.connect(self._on_double_click)
        layout.addWidget(self.tree)

        self.setLayout(layout)

        self.browse_btn.clicked.connect(self._browse)
        self.search_btn.clicked.connect(self.start_search)
        self.stop_btn.clicked.connect(self._stop_search)
        self.pattern_input.returnPressed.connect(self.start_search)

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

    def _on_result(self, filepath, lineno, line):
        if filepath not in self._file_items:
            item = QTreeWidgetItem(self.tree)
            item.setText(0, filepath)
            item.setForeground(0, QColor("#6897BB"))
            item.setData(0, Qt.ItemDataRole.UserRole, ('file', filepath, 0))
            self._file_items[filepath] = item

        parent = self._file_items[filepath]
        child = QTreeWidgetItem(parent)
        child.setText(0, f"  行 {lineno}")
        child.setText(1, line.strip())
        child.setForeground(0, QColor("#808080"))
        child.setData(0, Qt.ItemDataRole.UserRole, ('line', filepath, lineno))
        parent.setExpanded(True)

    def _on_finished(self, count):
        self.search_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        files = len(self._file_items)
        self.result_label.setText(f"{count} 件 / {files} ファイル")

    def _on_double_click(self, item, _col):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data and data[0] == 'line':
            self.open_file_requested.emit(data[1], data[2])


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
}

# 表示用 (UI のコンボ等で使う)
SUPPORTED_LANGUAGES = ['text', 'python', 'javascript', 'sql', 'log']


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


class EditorTab(QWidget):
    content_changed = pyqtSignal()

    def __init__(self, content='', filename='無題', file_path=None):
        super().__init__()
        self.filename = filename
        self.file_path = file_path
        self.is_modified = False
        self._original_lines: list[str] = content.splitlines()

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        self.editor = CodeEditor()
        self._apply_editor_style()

        # コンテンツを先にセットしてからハイライターを接続する。
        # 逆順だと setPlainText 時にブロック状態が未初期化のまま
        # ハイライトが走り、ブロックコメント状態の引き継ぎが失敗する場合がある。
        if content:
            self.editor.setPlainText(content)

        lang = detect_language(filename)
        self.highlighter = SyntaxHighlighter(self.editor.document(), lang)
        # document 接続直後に明示的に全行を再ハイライト
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
        self.editor.document().contentsChanged.connect(self._diff_timer.start)

    def reset_original(self):
        """保存後に基準行を更新してガターをクリアする"""
        self._original_lines = self.editor.toPlainText().splitlines()
        self.editor.set_change_map({})

    def _apply_editor_style(self):
        t = _theme()
        self.editor.setStyleSheet(f"""
            QPlainTextEdit {{
                background-color: {t['editor_bg']};
                color: {t['text']};
                border: none;
                selection-background-color: {t['selection']};
            }}
        """)

    def apply_settings(self):
        """テーマ・フォントサイズ変更を反映"""
        fs = SETTINGS.get('editor_font_size', 11)
        font = QFont("Consolas", fs)
        font.setFixedPitch(True)
        self.editor.setFont(font)
        self.editor.setTabStopDistance(
            4 * self.editor.fontMetrics().horizontalAdvance(' ')
        )
        self._apply_editor_style()
        # 行番号エリアを再描画 (ガター色も theme 連動にしたい場合は CodeEditor を修正)
        self.editor.line_number_area.update()

    def _on_modified(self, modified):
        self.is_modified = modified
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
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(4)

        lay.addWidget(self._section_label("フォントサイズ"))
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
        lay.addLayout(grid)

        lay.addWidget(self._section_label("テーマ"))
        theme_row = QHBoxLayout()
        theme_row.addWidget(QLabel("プリセット:"))
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(list(_THEME_PRESETS.keys()))
        cur_theme = SETTINGS.get('theme', 'Dark')
        i = self.theme_combo.findText(cur_theme)
        if i >= 0:
            self.theme_combo.setCurrentIndex(i)
        theme_row.addWidget(self.theme_combo, 1)
        lay.addLayout(theme_row)

        lay.addStretch()

        btns = QHBoxLayout()
        reset = QPushButton("デフォルトに戻す")
        reset.clicked.connect(self._reset_defaults)
        btns.addWidget(reset)
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
            QComboBox{{background:{t['control_bg']};color:{t['text']};
                      border:1px solid {t['border']};padding:2px 4px;min-height:24px;}}
            QComboBox QAbstractItemView{{background:{t['panel_bg']};color:{t['text']};
                                        selection-background-color:{t['selection']};}}
            QPushButton{{background:{t['control_bg']};color:{t['text']};border:none;
                        padding:4px 12px;border-radius:2px;}}
            QPushButton:hover{{background:{t['control_hover']};}}
            QPushButton:default{{background:{t['selection']};color:{t['text']};}}
        """)

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

    def accept(self):
        for k, sp in self._spinners.items():
            SETTINGS[k] = sp.value()
        SETTINGS['theme'] = self.theme_combo.currentText()
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
        self.grep_panel.hide()

        self.bookmark_panel = BookmarkPanel()
        self.bookmark_panel.jump_requested.connect(self._jump_to_bookmark)
        self.bookmark_panel.hide()

        # 下部エリアを横スプリッターで Grep | Bookmark に分割
        self.bottom_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.bottom_splitter.addWidget(self.grep_panel)
        self.bottom_splitter.addWidget(self.bookmark_panel)
        self.bottom_splitter.hide()

        self.v_splitter.addWidget(self.tabs)
        self.v_splitter.addWidget(self.bottom_splitter)
        self.v_splitter.setStretchFactor(0, 3)
        self.v_splitter.setStretchFactor(1, 1)

        self.splitter.addWidget(self.ftp_panel)
        self.splitter.addWidget(self.v_splitter)
        self.splitter.setStretchFactor(1, 1)
        self.setCentralWidget(self.splitter)

        self.pos_label = QLabel("行: 1  列: 1")
        # 言語切替コンボ (ステータスバーで現在の言語を確認・変更)
        self.lang_combo = QComboBox()
        self.lang_combo.addItems(SUPPORTED_LANGUAGES)
        self.lang_combo.setToolTip("現在のタブのシンタックスハイライト言語")
        self.lang_combo.setFixedWidth(110)
        self.lang_combo.currentTextChanged.connect(self._on_language_changed)
        sb = QStatusBar()
        sb.addPermanentWidget(self.pos_label)
        sb.addPermanentWidget(QLabel("言語:"))
        sb.addPermanentWidget(self.lang_combo)
        self.setStatusBar(sb)

    def _setup_menu(self):
        mb = self.menuBar()

        # ファイルメニュー
        fm = mb.addMenu("ファイル(&F)")
        self._add_action(fm, "新規(&N)", QKeySequence.StandardKey.New, self.new_file)
        self._add_action(fm, "開く(&O)...", QKeySequence.StandardKey.Open, self.open_file)
        fm.addSeparator()
        self._add_action(fm, "保存(&S)", QKeySequence.StandardKey.Save, self.save_file)
        self._add_action(fm, "名前を付けて保存(&A)...", QKeySequence("Ctrl+Shift+S"), self.save_file_as)
        self._add_action(fm, "全て保存(&L)", QKeySequence("Ctrl+Alt+S"), self.save_all)
        self._add_action(fm, "全て保存して終了(&X)", QKeySequence("Ctrl+Alt+Q"), self.save_all_and_exit)
        fm.addSeparator()
        self._add_action(fm, "終了(&Q)", QKeySequence("Ctrl+Q"), self.close)

        # 編集メニュー
        em = mb.addMenu("編集(&E)")
        self._add_action(em, "元に戻す(&U)", QKeySequence.StandardKey.Undo,
                         lambda: self.current_editor() and self.current_editor().undo())
        self._add_action(em, "やり直し(&R)", QKeySequence.StandardKey.Redo,
                         lambda: self.current_editor() and self.current_editor().redo())
        em.addSeparator()
        self._add_action(em, "切り取り(&X)", QKeySequence.StandardKey.Cut,
                         lambda: self.current_editor() and self.current_editor().cut())
        self._add_action(em, "コピー(&C)", QKeySequence.StandardKey.Copy,
                         lambda: self.current_editor() and self.current_editor().copy())
        self._add_action(em, "貼り付け(&V)", QKeySequence.StandardKey.Paste,
                         lambda: self.current_editor() and self.current_editor().paste())
        em.addSeparator()
        self._add_action(em, "検索・置換(&H)...", QKeySequence("Ctrl+H"), self._show_search)
        self._add_action(em, "検索(&F)...", QKeySequence("Ctrl+F"), self._show_search)
        self._add_action(em, "選択語を検索(Ctrl+F3)", QKeySequence("Ctrl+F3"), self._search_selection_next)
        self._add_action(em, "ファイル内Grep検索(&G)...", QKeySequence("Ctrl+Shift+F"), self._show_grep)
        em.addSeparator()
        self._add_action(em, "行へジャンプ(&L)...", QKeySequence("Ctrl+G"), self._show_goto_line)
        em.addSeparator()
        self._add_action(em, "次の変更箇所(&N)", QKeySequence("Alt+Down"), self._next_change)
        self._add_action(em, "前の変更箇所(&P)", QKeySequence("Alt+Up"), self._prev_change)

        # ブックマークメニュー
        bm = mb.addMenu("ブックマーク(&B)")
        self._add_action(bm, "マーク切替(&F2)", QKeySequence("F2"), self._toggle_bookmark)
        self._add_action(bm, "次のブックマーク(&F3)", QKeySequence("F3"), self._next_bookmark)
        self._add_action(bm, "前のブックマーク(Shift+F3)", QKeySequence("Shift+F3"), self._prev_bookmark)
        bm.addSeparator()
        self._add_action(bm, "次のエラー行(&E)", QKeySequence("Ctrl+E"), self._next_error)
        self._add_action(bm, "前のエラー行(Ctrl+Shift+E)", QKeySequence("Ctrl+Shift+E"), self._prev_error)
        bm.addSeparator()
        self._add_action(bm, "ブックマーク一覧(&L)", QKeySequence("Ctrl+B"), self._show_bookmarks)

        # 表示メニュー
        vm = mb.addMenu("表示(&V)")
        act = QAction("FTPパネル(&T)", self)
        act.setCheckable(True)
        act.setShortcut(QKeySequence("Ctrl+T"))
        act.triggered.connect(self._toggle_ftp)
        vm.addAction(act)

        grep_act = QAction("Grepパネル(&G)", self)
        grep_act.setCheckable(True)
        grep_act.setShortcut(QKeySequence("Ctrl+Shift+F"))
        grep_act.triggered.connect(self._show_grep)
        vm.addAction(grep_act)

        # ツールメニュー
        tm = mb.addMenu("ツール(&T)")
        self._add_action(tm, "ログからSQL抽出・整形(&S)...", QKeySequence("Ctrl+Shift+Q"), self._show_sql_extract)
        tm.addSeparator()
        self._add_action(tm, "⚙ 設定(&P)...", QKeySequence("Ctrl+,"), self._open_settings)

    def _open_settings(self):
        dlg = SettingsDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._apply_all_settings()

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
        if isinstance(shortcut, QKeySequence.StandardKey):
            act.setShortcut(QKeySequence(shortcut))
        else:
            act.setShortcut(shortcut)
        act.triggered.connect(slot)
        menu.addAction(act)

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
            QTabWidget::pane {{ border: none; background: {t['editor_bg']}; }}
            QTabBar::tab {{
                background: {t['control_bg']}; color: {t['text']};
                padding: 3px 10px; border: none; min-width: 60px;
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
            QListWidget::item:selected {{ background: {t['selection']}; }}
            QListWidget::item:hover {{ background: {t['control_hover']}; }}
            QTreeWidget {{
                background: {t['panel_bg']}; color: {t['text']}; border: none;
                outline: none; font-size: {ui_fs}px;
            }}
            QTreeWidget::item {{ padding: 1px 0; }}
            QTreeWidget::item:selected {{ background: {t['selection']}; }}
            QTreeWidget::item:hover {{ background: {t['control_hover']}; }}
            QHeaderView::section {{
                background: {t['control_bg']}; color: {t['text']};
                border: none; padding: 2px 4px;
            }}
            QComboBox {{
                background: {t['control_bg']}; color: {t['text']};
                border: 1px solid {t['border']}; padding: 1px 3px;
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
            QToolTip {{ background-color: #2b2b2b; color: #ffffff;
                       border: 1px solid #666; padding: 3px 6px; }}
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
            "テキストファイル (*.txt *.md)",
        )
        for path in paths:
            self._load_file(path)

    def _load_file(self, path):
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
            filename = os.path.basename(path)
            tab = EditorTab(content, filename, path)
            self._connect_tab(tab)
            idx = self.tabs.addTab(tab, filename)
            self.tabs.setCurrentIndex(idx)
            tab.editor.document().setModified(False)
            self._watch_path(path)
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
            with open(local_path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
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
            tab = self.tabs.widget(existing_idx)
            cur_block = tab.editor.textCursor().blockNumber()
            tab.editor.setPlainText(content)
            tab._original_lines = content.splitlines()
            tab.editor.document().setModified(False)
            tab.highlighter.rehighlight()
            # スクロール位置を元の行に近づける
            self._jump_to_line(tab.editor, cur_block + 1)
            self.tabs.setCurrentIndex(existing_idx)
            self.statusBar().showMessage(
                f"[FTP] {filename} をリロードしました", 3000
            )
            return

        # 新規タブ
        tab = EditorTab(content, filename, local_path)
        self._connect_tab(tab)
        idx = self.tabs.addTab(tab, f"[FTP] {filename}")
        self.tabs.setCurrentIndex(idx)
        tab.editor.document().setModified(False)
        self._watch_path(local_path)

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
        tab.editor.bookmark_toggled.connect(lambda *_: self._refresh_bookmarks())

    def save_file(self):
        tab = self.current_tab()
        if not tab:
            return
        if tab.file_path:
            self._write_file(tab, tab.file_path)
        else:
            self.save_file_as()

    def save_file_as(self):
        tab = self.current_tab()
        if not tab:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "名前を付けて保存", tab.filename,
            "すべてのファイル (*);;"
            "Pythonファイル (*.py);;"
            "テキストファイル (*.txt)",
        )
        if path:
            self._write_file(tab, path)

    def _write_file(self, tab, path):
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(tab.editor.toPlainText())
            tab.file_path = path
            tab.filename = os.path.basename(path)
            idx = self.tabs.indexOf(tab)
            self.tabs.setTabText(idx, tab.filename)
            tab.editor.document().setModified(False)
            tab.reset_original()  # 保存後はガターをリセット
            self.statusBar().showMessage(f"保存しました: {path}", 3000)
            # 自分が書いたファイルの fileChanged を 1 秒間無視
            self._self_write_paths.add(path)
            self._self_write_clear_timer.start(1000)
            self._watch_path(path)   # 監視継続 (Qt が一旦解除する場合あり)
        except Exception as e:
            QMessageBox.critical(self, "保存エラー", str(e))

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
                with open(path, 'r', encoding='utf-8', errors='replace') as f:
                    new_content = f.read()
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
        """タブの内容を新コンテンツに置き換え (カーソル位置をなるべく保持)"""
        cur_block = tab.editor.textCursor().blockNumber()
        tab.editor.setPlainText(new_content)
        tab._original_lines = new_content.splitlines()
        tab.editor.document().setModified(False)
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

    def _close_tab(self, idx):
        tab = self.tabs.widget(idx)
        if isinstance(tab, EditorTab) and tab.is_modified:
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

    def _show_search(self):
        tab = self.current_tab()
        if not tab:
            return
        # 選択中なら自動入力 (改行を含む選択は最初の行だけ)
        sel = tab.editor.textCursor().selectedText()
        # Qt の selectedText は改行を U+2029 で返す
        for sep in (' ', ' ', '\n', '\r'):
            if sep in sel:
                sel = sel.split(sep)[0]
                break
        tab.search_bar.show_bar(initial_text=sel if sel else None)

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
        self.grep_panel.show()
        self.bottom_splitter.show()
        tab = self.current_tab()
        if tab and tab.file_path:
            self.grep_panel.set_directory(os.path.dirname(tab.file_path))
        self.grep_panel.pattern_input.setFocus()

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
        self.bottom_splitter.show()
        self._refresh_bookmarks()

    def _show_sql_extract(self):
        tab = self.current_tab()
        if not tab:
            QMessageBox.information(self, "情報", "ファイルを開いてください。")
            return
        content = tab.editor.toPlainText()
        if not content.strip():
            QMessageBox.information(self, "情報", "ファイルが空です。")
            return
        dlg = SqlExtractDialog(content, tab.filename, parent=self)
        dlg.open_sql_requested.connect(self._open_sql_content)
        dlg.exec()

    def _open_sql_content(self, content: str, filename: str):
        tab = EditorTab(content, filename)
        self._connect_tab(tab)
        idx = self.tabs.addTab(tab, filename)
        self.tabs.setCurrentIndex(idx)

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

    def _open_file_at_line(self, filepath, lineno):
        # 既に開いているか確認
        for i in range(self.tabs.count()):
            tab = self.tabs.widget(i)
            if isinstance(tab, EditorTab) and tab.file_path == filepath:
                self.tabs.setCurrentIndex(i)
                self._jump_to_line(tab.editor, lineno)
                return
        # 新しく開く
        self._load_file(filepath)
        tab = self.current_tab()
        if tab:
            self._jump_to_line(tab.editor, lineno)

    def _jump_to_line(self, editor, lineno):
        block = editor.document().findBlockByLineNumber(lineno - 1)
        if block.isValid():
            cursor = editor.textCursor()
            cursor.setPosition(block.position())
            editor.setTextCursor(cursor)
            editor.centerCursor()

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

    def _on_content_changed(self):
        tab = self.current_tab()
        if not tab:
            return
        idx = self.tabs.indexOf(tab)
        title = tab.filename
        if tab.is_modified:
            title = f"● {title}"
        self.tabs.setTabText(idx, title)

    def _on_tab_changed(self, _):
        self._update_cursor()
        self._sync_language_combo()

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
        for i in range(self.tabs.count()):
            tab = self.tabs.widget(i)
            if isinstance(tab, EditorTab) and tab.is_modified:
                ans = QMessageBox.question(
                    self, "終了確認",
                    "保存されていない変更があります。終了しますか？",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if ans == QMessageBox.StandardButton.No:
                    event.ignore()
                    return
                break
        event.accept()


# ---------------------------------------------------------------------------
# SQL抽出・整形ダイアログ
# ---------------------------------------------------------------------------

# ログからSQLを抽出するための既知プレフィックスと継続行パターン
_SQL_PREFIXES = [
    r'Hibernate\s*:\s*',
    r'SQL\s*:\s*',
    r'==>\s*Preparing\s*:\s*',
    r'(?:Executing|Executed)\s+(?:query|statement|SQL)\s*:\s*',
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
_LOG_LINE_START = re.compile(
    r'^\d{4}[-/]\d{2}[-/]\d{2}|^\s*\d{2}:\d{2}:\d{2}|\b(ERROR|WARN|INFO|DEBUG|TRACE)\b'
)


def _try_format_sql(sql: str, indent: int, keyword_case: str) -> str:
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

        # プレフィックスを除去してSQLを探す
        body = prefix_re.sub('', stripped, count=1).strip() if prefix_re.search(stripped) else stripped

        if _SQL_START_KW.search(body):
            # 前のSQLを確定
            flush()
            current_lineno = lineno
            current_sql_parts.append(body)
        elif current_sql_parts:
            # 継続行かどうか
            if _LOG_LINE_START.match(stripped) or not stripped:
                # 新しいログ行 or 空行 → SQL終了
                flush()
            else:
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


class SqlExtractDialog(QDialog):
    open_sql_requested = pyqtSignal(str, str)  # content, filename

    def __init__(self, log_content: str, source_name: str = '', parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"SQL抽出・整形 — {source_name}")
        self.setMinimumSize(1000, 650)
        self.resize(1200, 720)
        self._log_content = log_content
        self._extracted: list[dict] = []
        self._build_ui()
        self._extract()

    def _build_ui(self):
        main = QVBoxLayout()
        main.setSpacing(3)
        main.setContentsMargins(6, 6, 6, 6)

        # ─── オプションバー ───────────────────────────────────────────
        opt_bar = QHBoxLayout()
        opt_bar.addWidget(QLabel("追加プレフィックス:"))
        self.prefix_input = QLineEdit()
        self.prefix_input.setPlaceholderText("例: MyPrefix:, Exec:")
        opt_bar.addWidget(self.prefix_input, 2)

        opt_bar.addWidget(QLabel("キーワード:"))
        self.kw_combo = QComboBox()
        self.kw_combo.addItems(["upper", "lower", "capitalize"])
        opt_bar.addWidget(self.kw_combo)

        opt_bar.addWidget(QLabel("インデント:"))
        self.indent_spin = QSpinBox()
        self.indent_spin.setRange(2, 8)
        self.indent_spin.setValue(4)
        self.indent_spin.setMaximumWidth(50)
        opt_bar.addWidget(self.indent_spin)

        self.subst_check = QCheckBox("パラメータ置換")
        self.subst_check.setToolTip("?プレースホルダーをバインド値で置換する")
        self.subst_check.setChecked(True)
        opt_bar.addWidget(self.subst_check)

        extract_btn = QPushButton("再抽出")
        extract_btn.clicked.connect(self._extract)
        opt_bar.addWidget(extract_btn)

        self.count_label = QLabel("0 件")
        self.count_label.setStyleSheet("color: #808080;")
        opt_bar.addWidget(self.count_label)
        main.addLayout(opt_bar, 0)

        # ─── メインスプリッター：左=リスト / 右=プレビュー ───────────
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # 左：抽出リスト
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 2, 0)
        ll.setSpacing(2)
        ll.addWidget(QLabel("抽出されたSQL:"))
        self.sql_list = QListWidget()
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
        rl.addLayout(preview_header)

        self.preview = QPlainTextEdit()
        self.preview.setFont(QFont("Consolas", 10))
        self.preview.setStyleSheet(
            "background:#2b2b2b; color:#a9b7c6; border:none; selection-background-color:#214283;"
        )
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
        self.setStyleSheet("""
            QDialog { background: #2b2b2b; }
            QLabel  { color: #a9b7c6; }
            QPushButton { background:#4a4a4a; color:#a9b7c6; border:none; padding:2px 8px; border-radius:2px; }
            QPushButton:hover { background:#5a5a5a; }
            QListWidget { background:#1e1e1e; color:#a9b7c6; border:none; }
            QListWidget::item { padding:1px 2px; }
            QListWidget::item:selected { background:#214283; }
            QListWidget::item:hover { background:#3a3a3a; }
            QLineEdit { background:#3a3a3a; color:#a9b7c6; border:1px solid #555; padding:1px 3px; }
            QComboBox { background:#3a3a3a; color:#a9b7c6; border:1px solid #555; padding:1px 3px; }
            QComboBox QAbstractItemView { background:#2b2b2b; color:#a9b7c6; selection-background-color:#214283; }
            QSpinBox  { background:#3a3a3a; color:#a9b7c6; border:1px solid #555; padding:1px 3px; }
            QCheckBox { color:#a9b7c6; }
            QSplitter::handle { background:#3a3a3a; width:4px; }
        """)

    # ─── 抽出・整形ロジック ────────────────────────────────────────────

    def _extract(self):
        extras = [p.strip() for p in self.prefix_input.text().split(',') if p.strip()]
        self._extracted = _extract_sql_from_log(self._log_content, extras)
        self.count_label.setText(f"{len(self._extracted)} 件")
        self._update_list()

    def _update_list(self):
        self.sql_list.clear()
        for i, entry in enumerate(self._extracted):
            preview = entry['sql'][:70].replace('\n', ' ')
            if len(entry['sql']) > 70:
                preview += '…'
            has_params = bool(entry['params'])
            marker = ' [?]' if '?' in entry['sql'] and has_params else ''
            item = QListWidgetItem(f"  {i+1:>3}.{marker}  {preview}")
            item.setToolTip(f"ログ行 {entry['lineno']}")
            if re.match(r'\s*(SELECT|WITH)\b', entry['sql'], re.IGNORECASE):
                item.setForeground(QColor("#6A8759"))
            elif re.match(r'\s*(INSERT|MERGE)\b', entry['sql'], re.IGNORECASE):
                item.setForeground(QColor("#6897BB"))
            elif re.match(r'\s*(UPDATE|DELETE)\b', entry['sql'], re.IGNORECASE):
                item.setForeground(QColor("#E8B26A"))
            self.sql_list.addItem(item)
        if self._extracted:
            self.sql_list.setCurrentRow(0)

    def _on_row_changed(self, row):
        if 0 <= row < len(self._extracted):
            self._show_entry(self._extracted[row])

    def _show_entry(self, entry: dict):
        sql = entry['sql']
        params = entry['params']

        if self.subst_check.isChecked() and params:
            sql = _substitute_params(sql, params)

        formatted = _try_format_sql(sql, self.indent_spin.value(), self.kw_combo.currentText())
        self.preview.setPlainText(formatted)
        self.lineno_label.setText(f"ログ行: {entry['lineno']}")

        if params:
            param_txt = '  '.join(f"[{k}]={v}" for k, v in sorted(params.items()))
            self.param_label.setText(f"バインドパラメータ: {param_txt}")
        else:
            self.param_label.setText("")

    def _reformat(self):
        row = self.sql_list.currentRow()
        if 0 <= row < len(self._extracted):
            self._show_entry(self._extracted[row])

    # ─── タブ操作 ─────────────────────────────────────────────────────

    def _open_one(self):
        text = self.preview.toPlainText().strip()
        if not text:
            return
        row = self.sql_list.currentRow()
        fname = f"query_{row+1}.sql"
        self.open_sql_requested.emit(text, fname)

    def _open_all(self):
        if not self._extracted:
            return
        parts = []
        for i, entry in enumerate(self._extracted, 1):
            sql = entry['sql']
            if self.subst_check.isChecked() and entry['params']:
                sql = _substitute_params(sql, entry['params'])
            formatted = _try_format_sql(sql, self.indent_spin.value(), self.kw_combo.currentText())
            parts.append(f"-- ===== Query {i}  (log line {entry['lineno']}) =====\n{formatted}")
        self.open_sql_requested.emit('\n\n'.join(parts), "all_queries.sql")

    def _copy(self):
        text = self.preview.toPlainText().strip()
        if text:
            QApplication.clipboard().setText(text)
            self.param_label.setText("クリップボードにコピーしました")


# ---------------------------------------------------------------------------
# エントリーポイント
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    # 起動時の一時ファイルクリーンアップ (FTP ダウンロード分)
    import tempfile as _tempfile
    try:
        _ftp_tmp = os.path.join(_tempfile.gettempdir(), 'text_editor_ftp')
        _cleanup_old_temp_files(_ftp_tmp)
    except Exception:
        pass

    app = QApplication(sys.argv)
    app.setApplicationName("Sora Editor")
    try:
        from app_icons import text_editor_icon
        app.setWindowIcon(text_editor_icon())
    except Exception:
        pass
    window = MainWindow()
    window.show()
    # コマンドライン引数で指定されたファイルを開く (タブとして追加)
    for arg in sys.argv[1:]:
        if os.path.isfile(arg):
            window._load_file(arg)
    sys.exit(app.exec())
