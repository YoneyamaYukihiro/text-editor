#!/usr/bin/env python3
"""アプリアイコン生成モジュール

各アプリの main から `ssh_log_viewer_icon()` / `text_editor_icon()` を呼んで
QIcon を取得する。

このファイルを直接実行すると assets/ に PNG ファイル群を生成する:
    python app_icons.py
"""
import os
import sys

from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import (
    QBrush, QColor, QFont, QIcon, QLinearGradient, QPainter, QPen, QPixmap,
)


# ---------------------------------------------------------------------------
# 共通ユーティリティ
# ---------------------------------------------------------------------------

def _new_pixmap(size: int) -> tuple[QPixmap, QPainter]:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    return pixmap, p


def _rounded_bg(p: QPainter, size: int,
                top_color: str, bottom_color: str,
                border_color: str, radius_ratio: float = 0.18):
    """グラデーション背景の角丸正方形を描画"""
    inset = max(2, size // 32)
    rect = QRectF(inset, inset, size - 2 * inset, size - 2 * inset)
    grad = QLinearGradient(0, rect.top(), 0, rect.bottom())
    grad.setColorAt(0, QColor(top_color))
    grad.setColorAt(1, QColor(bottom_color))
    p.setBrush(QBrush(grad))
    p.setPen(QPen(QColor(border_color), max(1, size // 128)))
    r = size * radius_ratio
    p.drawRoundedRect(rect, r, r)


# ---------------------------------------------------------------------------
# SSH/Telnet Log Viewer アイコン
# ---------------------------------------------------------------------------
# テーマ: ターミナル風。緑の `>` プロンプト + 青の_カーソル + ERROR/WARN/INFO のログバー

def ssh_log_viewer_pixmap(size: int = 256) -> QPixmap:
    pixmap, p = _new_pixmap(size)
    _rounded_bg(p, size,
                top_color='#1f1f1f',
                bottom_color='#0c0c0c',
                border_color='#3a5a3a')

    # `>` プロンプト記号
    p.setPen(QColor('#5FBF5F'))
    f = QFont('Consolas', max(8, int(size * 0.32)))
    f.setBold(True)
    p.setFont(f)
    prompt_rect = QRectF(size * 0.10, size * 0.10, size * 0.45, size * 0.45)
    p.drawText(prompt_rect,
               Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
               '>')

    # `_` カーソル (点滅イメージ)
    cur_x = size * 0.46
    cur_w = size * 0.20
    cur_y = size * 0.42
    cur_h = max(2, size * 0.04)
    p.fillRect(QRectF(cur_x, cur_y, cur_w, cur_h), QColor('#4A9EFF'))

    # ログ行 (ERROR/WARN/INFO 風の3本バー)
    bars = [
        ('#CF6679', 0.62, 0.58),   # 赤系: ERROR
        ('#E8B26A', 0.74, 0.46),   # 黄系: WARN
        ('#6A9F6A', 0.84, 0.66),   # 緑系: INFO
    ]
    bar_h = max(2, size * 0.045)
    for color, y_ratio, w_ratio in bars:
        p.fillRect(
            QRectF(size * 0.16, size * y_ratio, size * w_ratio, bar_h),
            QColor(color),
        )
        # 行頭ドット (タイムスタンプ風)
        p.setBrush(QColor('#4EC9B0'))
        p.setPen(Qt.PenStyle.NoPen)
        dot_r = bar_h * 0.6
        p.drawEllipse(QRectF(size * 0.10, size * y_ratio + (bar_h - dot_r) / 2,
                             dot_r, dot_r))

    p.end()
    return pixmap


def ssh_log_viewer_icon() -> QIcon:
    icon = QIcon()
    for sz in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(ssh_log_viewer_pixmap(sz))
    return icon


# ---------------------------------------------------------------------------
# Text Editor アイコン
# ---------------------------------------------------------------------------
# テーマ: ドキュメント + I-beam カーソル

def text_editor_pixmap(size: int = 256) -> QPixmap:
    pixmap, p = _new_pixmap(size)
    _rounded_bg(p, size,
                top_color='#21283a',
                bottom_color='#0e1320',
                border_color='#3a4d70')

    # 大きな "T"
    p.setPen(QColor('#E8E8E8'))
    f = QFont('Georgia', max(10, int(size * 0.42)))
    f.setBold(True)
    p.setFont(f)
    t_rect = QRectF(0, size * 0.06, size, size * 0.62)
    p.drawText(t_rect, Qt.AlignmentFlag.AlignCenter, 'T')

    # 右下に I-beam カーソル
    pen = QPen(QColor('#4A9EFF'), max(2, size // 56))
    p.setPen(pen)
    cur_cx = size * 0.74
    cur_top = size * 0.62
    cur_bot = size * 0.86
    arm = size * 0.05
    # 縦棒
    p.drawLine(int(cur_cx), int(cur_top), int(cur_cx), int(cur_bot))
    # 上下のセリフ
    p.drawLine(int(cur_cx - arm), int(cur_top), int(cur_cx + arm), int(cur_top))
    p.drawLine(int(cur_cx - arm), int(cur_bot), int(cur_cx + arm), int(cur_bot))

    # 下部に文字行を示す3本の薄いライン (装飾)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor('#3a4d70'))
    line_h = max(1, size * 0.022)
    for i, w_ratio in enumerate((0.50, 0.42, 0.32)):
        y = size * (0.76 + i * 0.06)
        if y + line_h > size * 0.94:
            break
        p.drawRect(QRectF(size * 0.14, y, size * w_ratio, line_h))

    p.end()
    return pixmap


def text_editor_icon() -> QIcon:
    icon = QIcon()
    for sz in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(text_editor_pixmap(sz))
    return icon


# ---------------------------------------------------------------------------
# CLI: PNG ファイルを assets/ に書き出し
# ---------------------------------------------------------------------------

def _save_png_set(pixmap_fn, base_name: str, out_dir: str):
    for sz in (16, 32, 48, 64, 128, 256):
        path = os.path.join(out_dir, f"{base_name}_{sz}.png")
        pixmap_fn(sz).save(path, 'PNG')
        print(f"  wrote {path}")


def _save_ico(pixmap_fn, base_name: str, out_dir: str):
    """Windows用 .ico を保存 (PyInstaller --icon に使用)。Qt が256pxまで対応。"""
    path = os.path.join(out_dir, f"{base_name}.ico")
    pixmap_fn(256).save(path, 'ICO')
    print(f"  wrote {path}")


def main():
    from PyQt6.QtWidgets import QApplication
    app = QApplication(sys.argv)

    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets')
    os.makedirs(out_dir, exist_ok=True)
    print(f"writing icons to {out_dir}/")
    _save_png_set(ssh_log_viewer_pixmap, 'ssh_log_viewer', out_dir)
    _save_png_set(text_editor_pixmap,    'text_editor',    out_dir)
    _save_ico(ssh_log_viewer_pixmap, 'ssh_log_viewer', out_dir)
    _save_ico(text_editor_pixmap,    'text_editor',    out_dir)
    print("done.")


if __name__ == '__main__':
    main()
