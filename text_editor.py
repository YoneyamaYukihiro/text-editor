#!/usr/bin/env python3
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
from PyQt6.QtCore import Qt, QRegularExpression, pyqtSignal, QSize, QThread, QTimer
from PyQt6.QtGui import (
    QFont, QColor, QTextCharFormat, QSyntaxHighlighter,
    QKeySequence, QAction, QPainter, QTextFormat, QTextDocument,
)


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

    _GUTTER_W   = 4    # 変更バー幅(px)
    _BOOKMARK_W = 12   # ブックマーク列幅(px)
    _GUTTER_COLORS = {
        'added':    QColor("#587A58"),
        'modified': QColor("#8A7040"),
        'deleted':  QColor("#8A3030"),
    }
    _BOOKMARK_COLOR = QColor("#4A9EFF")

    def __init__(self):
        super().__init__()
        self.line_number_area = LineNumberArea(self)
        self._change_map: dict[int, str] = {}
        self._bookmarks: set[int] = set()
        self._search_selections: list = []

        font = QFont("Consolas", 11)
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
        painter.fillRect(event.rect(), QColor("#2b2b2b"))

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
                painter.setPen(QColor("#606060"))
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
        if not self.isReadOnly():
            sel = QTextEdit.ExtraSelection()
            sel.format.setBackground(QColor("#3a3a3a"))
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
                # HTTPステータスコード 4xx/5xx
                (r'\b[45]\d{2}\b',                       '#FF7070'),
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

        # 文字列リテラル（緑）
        str_fmt = self._fmt('#6A8759')
        for pat in spec.get('strings', []):
            self._rules.append((QRegularExpression(pat), str_fmt))

        # 単行コメント
        if 'comment' in spec:
            self._rules.append((QRegularExpression(spec['comment']), self._comment_fmt))

        # ブロックコメントは highlightBlock で状態管理するため別保持
        if 'block_comment' in spec:
            self._block_comment_spec = spec['block_comment']

        # 数値（青）— log は inline で個別指定するためスキップ
        if 'line_levels' not in spec:
            self._rules.append((QRegularExpression(r'\b\d+\.?\d*\b'), self._fmt('#6897BB')))

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
        self.hide()

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
        self.setStyleSheet("""
            QWidget   { background: #333333; }
            QLabel    { color: #a9b7c6; }
            QComboBox { background:#3a3a3a; color:#a9b7c6; border:1px solid #555; padding:1px 3px; }
            QComboBox QAbstractItemView { background:#2b2b2b; color:#a9b7c6;
                                          selection-background-color:#214283; }
            QComboBox::drop-down { border:none; width:16px; }
        """)
        self.setMaximumHeight(32)

        # シグナル
        self.search_input.lineEdit().textChanged.connect(self._update_highlights)
        self.search_input.lineEdit().returnPressed.connect(self._on_return)
        self.search_input.currentIndexChanged.connect(
            lambda _: self._update_highlights()
        )
        self.case_check.toggled.connect(self._update_highlights)
        self.regex_check.toggled.connect(self._update_highlights)
        self.next_btn.clicked.connect(self.find_next)
        self.prev_btn.clicked.connect(self.find_prev)
        self.replace_btn.clicked.connect(self.replace_current)
        self.replace_all_btn.clicked.connect(self.replace_all)
        close_btn.clicked.connect(self.close_bar)

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

    # --------------------------------------------------------------- 公開

    def show_bar(self):
        self.show()
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
        matches = list(pat.finditer(doc_text))

        if not matches:
            self._editor.set_search_highlights([])
            self.match_label.setText("見つからない")
            self.match_label.setStyleSheet("color:#FF7070; font-size:10px;")
            return

        fmt = QTextCharFormat()
        fmt.setBackground(QColor("#5a4a00"))
        fmt.setForeground(QColor("#FFE066"))
        selections = []
        for m in matches:
            sel = QTextEdit.ExtraSelection()
            sel.format = fmt
            cur = self._editor.textCursor()
            cur.setPosition(m.start())
            cur.setPosition(m.end(), cur.MoveMode.KeepAnchor)
            sel.cursor = cur
            selections.append(sel)

        self._editor.set_search_highlights(selections)
        self.match_label.setText(f"{len(matches)} 件")
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
    file_downloaded = pyqtSignal(str, str)  # content, filename

    def __init__(self, parent=None):
        super().__init__(parent)
        self.ftp = None
        self.current_path = '/'

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

    def _download(self, name):
        if not self.ftp:
            return
        try:
            buf = io.BytesIO()
            self.ftp.retrbinary(f'RETR {name}', buf.write)
            content = buf.getvalue().decode('utf-8', errors='replace')
            self.file_downloaded.emit(content, name)
        except Exception as e:
            QMessageBox.warning(self, "ダウンロードエラー", str(e))


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
    '.sql': 'sql',
    '.log': 'log', '.LOG': 'log',
}


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
        self.editor.setStyleSheet("""
            QPlainTextEdit {
                background-color: #2b2b2b;
                color: #a9b7c6;
                border: none;
                selection-background-color: #214283;
            }
        """)

        # コンテンツを先にセットしてからハイライターを接続する。
        # 逆順だと setPlainText 時にブロック状態が未初期化のまま
        # ハイライトが走り、ブロックコメント状態の引き継ぎが失敗する場合がある。
        if content:
            self.editor.setPlainText(content)

        ext = os.path.splitext(filename)[1].lower()
        lang = LANG_MAP.get(ext, 'text')
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
# メインウィンドウ
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("テキストエディタ")
        self.setMinimumSize(800, 500)
        self.resize(1200, 800)
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
        self.lang_label = QLabel("テキスト")
        sb = QStatusBar()
        sb.addPermanentWidget(self.pos_label)
        sb.addPermanentWidget(self.lang_label)
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
        self._add_action(em, "ファイル内Grep検索(&G)...", QKeySequence("Ctrl+Shift+F"), self._show_grep)

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

    def _add_action(self, menu, label, shortcut, slot):
        act = QAction(label, self)
        if isinstance(shortcut, QKeySequence.StandardKey):
            act.setShortcut(QKeySequence(shortcut))
        else:
            act.setShortcut(shortcut)
        act.triggered.connect(slot)
        menu.addAction(act)

    def _apply_theme(self):
        self.setStyleSheet("""
            QMainWindow { background: #1e1e1e; }
            QMenuBar { background: #2b2b2b; color: #a9b7c6; padding: 0; margin: 0; }
            QMenuBar::item { padding: 3px 8px; }
            QMenuBar::item:selected { background: #3a3a3a; }
            QMenu { background: #2b2b2b; color: #a9b7c6; border: 1px solid #3a3a3a; }
            QMenu::item { padding: 3px 20px 3px 12px; }
            QMenu::item:selected { background: #214283; }
            QTabWidget::pane { border: none; background: #2b2b2b; }
            QTabBar::tab {
                background: #3a3a3a; color: #a9b7c6;
                padding: 3px 10px; border: none; min-width: 60px;
            }
            QTabBar::tab:selected {
                background: #2b2b2b; color: #ffffff;
                border-top: 2px solid #4a9eff;
            }
            QTabBar::tab:hover { background: #4a4a4a; }
            QTabBar::close-button { subcontrol-position: right; }
            QStatusBar { background: #3a3a3a; color: #a9b7c6; padding: 0; }
            QStatusBar::item { border: none; }
            QPushButton {
                background: #4a4a4a; color: #a9b7c6;
                border: none; padding: 2px 8px; border-radius: 2px;
            }
            QPushButton:hover { background: #5a5a5a; }
            QPushButton:disabled { color: #606060; }
            QLineEdit {
                background: #3a3a3a; color: #a9b7c6;
                border: 1px solid #555; padding: 1px 3px;
            }
            QCheckBox { color: #a9b7c6; spacing: 4px; }
            QLabel { color: #a9b7c6; }
            QDialog { background: #2b2b2b; }
            QSplitter::handle { background: #3a3a3a; }
            QSplitter::handle:horizontal { width: 2px; }
            QSplitter::handle:vertical   { height: 2px; }
            QListWidget {
                background: #2b2b2b; color: #a9b7c6; border: none;
            }
            QListWidget::item { padding: 1px 2px; }
            QListWidget::item:selected { background: #214283; }
            QListWidget::item:hover { background: #3a3a3a; }
            QTreeWidget {
                background: #2b2b2b; color: #a9b7c6; border: none;
                outline: none;
            }
            QTreeWidget::item { padding: 1px 0; }
            QTreeWidget::item:selected { background: #214283; }
            QTreeWidget::item:hover { background: #3a3a3a; }
            QHeaderView::section {
                background: #3a3a3a; color: #a9b7c6;
                border: none; padding: 2px 4px;
            }
            QComboBox {
                background: #3a3a3a; color: #a9b7c6;
                border: 1px solid #555; padding: 1px 3px;
            }
            QComboBox::drop-down { border: none; width: 16px; }
            QComboBox QAbstractItemView {
                background: #2b2b2b; color: #a9b7c6;
                selection-background-color: #214283;
            }
            QSpinBox {
                background: #3a3a3a; color: #a9b7c6;
                border: 1px solid #555; padding: 1px 3px;
            }
            QGroupBox { color: #a9b7c6; border: 1px solid #444; margin-top: 6px; padding-top: 4px; }
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
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"ファイルを開けませんでした:\n{e}")

    def _open_ftp_content(self, content, filename):
        tab = EditorTab(content, filename)
        self._connect_tab(tab)
        idx = self.tabs.addTab(tab, f"[FTP] {filename}")
        self.tabs.setCurrentIndex(idx)

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
        except Exception as e:
            QMessageBox.critical(self, "保存エラー", str(e))

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
        self.tabs.removeTab(idx)
        if self.tabs.count() == 0:
            self.new_file()

    # --- その他のスロット ---

    def _show_search(self):
        tab = self.current_tab()
        if tab:
            tab.search_bar.show_bar()

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
    app = QApplication(sys.argv)
    app.setApplicationName("テキストエディタ")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
