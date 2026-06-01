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
    QBrush, QColor, QFont, QIcon, QLinearGradient, QPainter, QPainterPath,
    QPen, QPixmap,
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
# Multi-Server Log Viewer アイコン
# ---------------------------------------------------------------------------
# テーマ: ダーク背景に "MLV" を中央配置。

def ssh_log_viewer_pixmap(size: int = 256) -> QPixmap:
    pixmap, p = _new_pixmap(size)
    # ダーク背景 (上が少し明るく、下に向かって沈んでいくグラデ)
    _rounded_bg(p, size,
                top_color='#2c2c2c',
                bottom_color='#0c0c0c',
                border_color='#444444')

    # 極小サイズ (16px 等) は "MLV" 3文字が判読不能なので "M" 単体で大きく描く。
    # 色はログレベル赤系 (ERROR) でアイコンの世界観を保つ。
    if size <= 20:
        p.setPen(QColor('#CF6679'))
        pt = max(8, int(size * 0.85))
        f = QFont('Arial', pt)
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(0, 0, size, size),
                   Qt.AlignmentFlag.AlignCenter, 'M')
        p.end()
        return pixmap

    # 文字色: ダーク背景に映える明るいオフホワイト (大サイズの fallback 用)
    p.setPen(QColor('#E8E8E8'))

    # "MLV" — 中央配置 + ログレベル色のグラデーション (ERROR赤 → WARN黄 → INFO緑)
    pt = max(9, int(size * 0.34))
    f = QFont('Arial', pt)
    f.setBold(True)
    p.setFont(f)
    fm = p.fontMetrics()
    text = 'MLV'
    text_w = fm.horizontalAdvance(text)
    # 縦中央のための baseline 計算
    x = (size - text_w) / 2
    baseline_y = (size + fm.ascent() - fm.descent()) / 2

    # 文字形状を path に展開してグラデーションで fill
    path = QPainterPath()
    path.addText(float(x), float(baseline_y), f, text)
    grad = QLinearGradient(float(x), 0.0, float(x + text_w), 0.0)
    grad.setColorAt(0.0, QColor('#CF6679'))   # ERROR (赤)
    grad.setColorAt(0.5, QColor('#E8B26A'))   # WARN  (黄)
    grad.setColorAt(1.0, QColor('#6A9F6A'))   # INFO  (緑)
    p.setBrush(QBrush(grad))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawPath(path)

    p.end()
    return pixmap


def ssh_log_viewer_icon() -> QIcon:
    icon = QIcon()
    for sz in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(ssh_log_viewer_pixmap(sz))
    return icon


# ---------------------------------------------------------------------------
# Sora Editor アイコン
# ---------------------------------------------------------------------------
# テーマ: "Sora" = 空。晴天色のグラデ背景に、大きな "S" と小さな "ora"。

def text_editor_pixmap(size: int = 256) -> QPixmap:
    pixmap, p = _new_pixmap(size)
    # 晴天色: 上が淡い水色、下がやや深い空色のグラデーション
    _rounded_bg(p, size,
                top_color='#BFE3F5',
                bottom_color='#5BA8D8',
                border_color='#3A87B0')

    # 文字色: 晴天背景に映える濃紺
    p.setPen(QColor('#0E2F5A'))

    # 極小サイズ (16px 等) は ora が判読不能なので S 単体でアイコンいっぱいに描く
    if size <= 20:
        small_pt = max(8, int(size * 0.85))
        f = QFont('Arial', small_pt)
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(0, 0, size, size),
                   Qt.AlignmentFlag.AlignCenter, 'S')
        p.end()
        return pixmap

    # 大きな S - アイコンの主役 (ほぼアイコンを埋める大きさ)
    big_pt = max(14, int(size * 0.72))
    f_big = QFont('Arial', big_pt)
    f_big.setBold(True)
    p.setFont(f_big)
    fm_big = p.fontMetrics()
    s_w = fm_big.horizontalAdvance('S')
    s_box = fm_big.boundingRect('S')          # baseline 基準の bounding rect
    s_top_neg = s_box.top()                    # 負値: baseline より上方向
    s_h = s_box.height()

    # 小さな ora — S にオーバーラップさせる
    small_pt = max(8, int(size * 0.24))
    f_small = QFont('Arial', small_pt)
    f_small.setBold(True)
    p.setFont(f_small)
    fm_small = p.fontMetrics()
    ora_w = fm_small.horizontalAdvance('ora')

    # コンポジット全体 (S + S にかぶる ora) を中央寄せ。
    # ora は S の幅の 68% 付近から開始 → o の左端だけが S にかぶる程度。
    ora_offset_in_s = s_w * 0.68
    composite_w = max(s_w, ora_offset_in_s + ora_w)
    s_left_x = (size - composite_w) / 2
    ora_x = s_left_x + ora_offset_in_s

    # S の視覚中央
    baseline_y = int(size / 2 - s_top_neg - s_h / 2)
    ora_baseline_y = baseline_y

    # まず S を描画 (濃紺)
    p.setFont(f_big)
    p.drawText(int(s_left_x), baseline_y, 'S')

    # ora を 2 段描画して「S と重なる部分だけ色違い」を表現する。
    # 1) 通常色 (濃紺) で全体を描く → S の外に出た部分はこの色で表示
    p.setFont(f_small)
    p.drawText(int(ora_x), ora_baseline_y, 'ora')

    # 2) S の文字形状を clip path にして、ora を明色で重ね描き
    #    → S と重なる部分だけ明色に切り替わって視認可能になる
    s_path = QPainterPath()
    s_path.addText(float(s_left_x), float(baseline_y), f_big, 'S')
    p.save()
    p.setClipPath(s_path)
    p.setPen(QColor('#BFE3F5'))  # 背景上端と同じ淡水色 = 「S を切り抜いた」印象
    p.drawText(int(ora_x), ora_baseline_y, 'ora')
    p.restore()

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
