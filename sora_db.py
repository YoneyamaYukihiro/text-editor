#!/usr/bin/env python3
"""Sora DB — Sora Editor の DBExecuteDialog を単独アプリ化したラッパー

このファイルは UI を自前で再実装せず、 text_editor.py で完成している
`DBExecuteDialog` (SSH 経由で sqlplus/mysql/psql 等を実行 + 結果を
4 モードで表示) をそのまま画面に出すだけの薄い起動ハーネス。

接続プロファイルは LogViewer / Sora と共通の
`~/.ssh_log_viewer_profiles.json` を共有する。

起動引数:
    sora_db.exe [--profile NAME] [--query "SELECT ..."]
他アプリ (Sora / LogViewer) から SQL を直接渡して起動できる。
"""
__version__ = "0.2.0"

import sys
import argparse
import os

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QAction
from PyQt6.QtWidgets import QApplication, QMainWindow, QMessageBox

# text_editor は同ディレクトリにある同名モジュール。 PyInstaller 配布時も
# `Sora DB.spec` の Analysis に追加すれば同梱される。
from text_editor import DBExecuteDialog


class _SoraDbWindow(QMainWindow):
    """DBExecuteDialog を中央に据える QMainWindow。
    QDialog 単独で出すと「ダイアログを閉じる = アプリ終了」 にしづらいので、
    QMainWindow + central widget 化して通常のアプリ感覚で扱えるようにする。"""

    def __init__(self, initial_query: str = '', initial_profile: str = ''):
        super().__init__()
        self.setWindowTitle(f"Sora DB  v{__version__}")
        self.resize(1100, 760)

        # DBExecuteDialog は QDialog だが、 内部レイアウトを central widget
        # として流用する。 `parent=self` で寿命を MainWindow に紐付け。
        self._dlg = DBExecuteDialog(initial_query, default_profile=initial_profile,
                                    parent=self)
        # QDialog はモーダル前提でフレーム描画されるため、 ウィンドウフラグを
        # 普通の Widget 寄りに整える (タイトルバーは MainWindow 側を使う)
        self._dlg.setWindowFlags(Qt.WindowType.Widget)
        self.setCentralWidget(self._dlg)

        # メニュー (ファイル / 実行 を最小限)
        mb = self.menuBar()
        fm = mb.addMenu("ファイル(&F)")
        a_quit = QAction("終了(&Q)", self)
        a_quit.setShortcut(QKeySequence("Ctrl+Q"))
        a_quit.triggered.connect(self.close)
        fm.addAction(a_quit)

    def closeEvent(self, event):
        # DBExecuteDialog 内のワーカースレッド等の後始末は元クラス側で処理される
        super().closeEvent(event)


def main():
    parser = argparse.ArgumentParser(description="Sora DB")
    parser.add_argument('--profile', default='', help='初期選択するプロファイル名')
    parser.add_argument('--query',   default='', help='初期投入する SQL')
    args, _qt_args = parser.parse_known_args()

    app = QApplication(sys.argv)
    app.setApplicationName("Sora DB")

    try:
        win = _SoraDbWindow(
            initial_query=args.query,
            initial_profile=args.profile,
        )
    except Exception as e:
        QMessageBox.critical(None, "起動エラー",
                             f"{type(e).__name__}: {e}")
        sys.exit(2)

    win.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
