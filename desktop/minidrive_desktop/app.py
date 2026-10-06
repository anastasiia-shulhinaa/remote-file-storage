"""Desktop application bootstrap."""

import sys

from PySide6.QtWidgets import QApplication

from minidrive_desktop.api import ApiClient
from minidrive_desktop.config import load_config
from minidrive_desktop.ui.main_window import MainWindow


def main() -> int:
    config = load_config()
    app = QApplication(sys.argv)
    app.setApplicationName("MiniDrive")

    with ApiClient(config.api_url, timeout=config.request_timeout_seconds) as api_client:
        window = MainWindow(api_client, config.api_url)
        window.show()
        window.check_backend()
        return app.exec()
