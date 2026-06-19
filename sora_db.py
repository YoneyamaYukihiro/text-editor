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
__version__ = "0.3.0"

import sys
import argparse
import os

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QAction
from PyQt6.QtWidgets import QApplication, QMainWindow, QMessageBox, QDialog

# text_editor / ssh_log_viewer は同ディレクトリにある同名モジュール。
# PyInstaller 配布時も `Sora DB.spec` の Analysis に追加されれば自動同梱。
from text_editor import DBExecuteDialog, _load_db_profiles
from ssh_log_viewer import SSHConnectDialog, ProfileManagerDialog


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

        # メニュー
        mb = self.menuBar()
        fm = mb.addMenu("ファイル(&F)")
        a_quit = QAction("終了(&Q)", self)
        a_quit.setShortcut(QKeySequence("Ctrl+Q"))
        a_quit.triggered.connect(self.close)
        fm.addAction(a_quit)

        sm = mb.addMenu("設定(&S)")
        a_conn = QAction("接続プロファイル管理(&P)...", self)
        a_conn.setShortcut(QKeySequence("Ctrl+,"))
        a_conn.setToolTip(
            "接続プロファイルを追加/編集/並び替え/削除します。\n"
            "ここで作成したプロファイルは LogViewer / Sora と共有されます。"
        )
        a_conn.triggered.connect(self._open_profile_manager)
        sm.addAction(a_conn)
        a_conn_new = QAction("新規接続プロファイルを追加(&N)...", self)
        a_conn_new.triggered.connect(self._open_profile_new)
        sm.addAction(a_conn_new)

    def _open_profile_manager(self):
        """LogViewer の ProfileManagerDialog を流用してプロファイルを管理 (名前
        変更/並び替え/削除)。 閉じた後に DBExecuteDialog のコンボを更新。"""
        try:
            dlg = ProfileManagerDialog(self)
        except Exception as e:
            QMessageBox.critical(self, "プロファイル管理エラー",
                                 f"{type(e).__name__}: {e}")
            return
        dlg.exec()
        self._reload_profiles_into_dialog()

    def _open_profile_new(self):
        """LogViewer の SSHConnectDialog を「保存目的のみ」 で開く。
        接続テスト + プロファイルとして保存できる。 connect() は走らない。"""
        try:
            dlg = SSHConnectDialog(self)
        except Exception as e:
            QMessageBox.critical(self, "接続ダイアログエラー",
                                 f"{type(e).__name__}: {e}")
            return
        # ダイアログ単体で動かす (= 接続せずに「保存」 だけ使う目的)。
        # SSHConnectDialog の「保存」 ボタンが ~/.ssh_log_viewer_profiles.json
        # に書き込みするので、 ここでは exec() の戻り値に関わらず再ロードする。
        dlg.exec()
        self._reload_profiles_into_dialog()

    def _reload_profiles_into_dialog(self):
        """DBExecuteDialog 内の _profiles と profile_combo を最新ファイル内容で
        更新 (新規追加/削除/改名を即座に反映)。"""
        try:
            self._dlg._profiles = _load_db_profiles()
            self._dlg._refresh_profile_combo()
        except Exception as e:
            # 失敗してもアプリは止めない (ステータスバー表示でも十分)
            self.statusBar().showMessage(
                f"プロファイル再ロード失敗: {e}", 5000
            )

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
