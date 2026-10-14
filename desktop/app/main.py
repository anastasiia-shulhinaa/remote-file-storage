"""MiniDrive Desktop Client.

Run from the desktop/ folder:  python -m app.main
The API address is configuration (app/config.py), not part of the user interface.
"""

import sys

from PySide6.QtCore import QSettings
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QDialog

from app import theme
from app.config import api_url
from app.i18n import set_language
from app.login_window import LoginWindow
from app.main_window import MainWindow


class DesktopApp:

    def __init__(self, qt_app: QApplication):
        self.qt_app = qt_app
        self.window: MainWindow | None = None
        self.api = None

    def show_login(self) -> None:
        if self.window is not None:
            self.window.close()
            self.window.deleteLater()
            self.window = None

        login = LoginWindow(api_url())
        if login.exec() != QDialog.Accepted or login.api is None:
            self.qt_app.quit()
            return
        self.api = login.api
        self.show_main()

    def show_main(self, folder_id: str | None = None) -> None:
        previous = self.window
        self.window = MainWindow(self.api, folder_id)
        self.window.logout_requested.connect(self.show_login)
        self.window.language_change_requested.connect(self.change_language)
        if previous is not None:
            self.window.setGeometry(previous.geometry())
            if previous.isMaximized():
                self.window.showMaximized()
        self.window.show()
        if previous is not None:
            previous.close()
            previous.deleteLater()

    def change_language(self, lang: str, folder_id: str) -> None:
        """Rebuild the window in the new language, keeping the open folder."""
        set_language(lang)
        self.show_main(folder_id or None)


def main() -> int:
    qt_app = QApplication(sys.argv)
    qt_app.setApplicationName("MiniDrive")
    qt_app.setOrganizationName("MiniDrive")
    qt_app.setApplicationDisplayName("MiniDrive")
    qt_app.setWindowIcon(QIcon(theme.brand_mark(64)))
    qt_app.setStyle("Fusion")
    qt_app.setStyleSheet(theme.STYLESHEET)
    # Ukrainian is the default interface language
    set_language(QSettings("MiniDrive", "Desktop").value("language", "uk"))
    # the main window quits explicitly; logging out closes it without quitting
    qt_app.setQuitOnLastWindowClosed(False)

    desktop = DesktopApp(qt_app)
    desktop.show_login()
    if desktop.window is None:
        return 0
    return qt_app.exec()


if __name__ == "__main__":
    sys.exit(main())
