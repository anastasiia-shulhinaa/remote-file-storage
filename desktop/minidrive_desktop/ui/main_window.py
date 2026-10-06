"""Main application window (shell only; features are added in later tasks)."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QLabel,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from minidrive_desktop.api import ApiClient, ApiError


class MainWindow(QMainWindow):
    def __init__(self, api_client: ApiClient, api_url: str) -> None:
        super().__init__()
        self._api_client = api_client

        self.setWindowTitle("MiniDrive")
        self.resize(900, 600)

        title = QLabel("MiniDrive")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 24px; font-weight: bold;")

        self.api_url_label = QLabel(f"Backend: {api_url}")
        self.api_url_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.status_label = QLabel("Backend status: not checked")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.check_button = QPushButton("Check connection")
        self.check_button.clicked.connect(self.check_backend)

        layout = QVBoxLayout()
        layout.addStretch()
        layout.addWidget(title)
        layout.addWidget(self.api_url_label)
        layout.addWidget(self.status_label)
        layout.addWidget(self.check_button, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addStretch()

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        self.statusBar().showMessage("Ready")

    def check_backend(self) -> None:
        try:
            health = self._api_client.health()
        except ApiError as exc:
            self.status_label.setText("Backend status: unavailable")
            self.statusBar().showMessage(str(exc))
            return

        self.status_label.setText(
            f"Backend status: {health.status} (v{health.version}, {health.environment})"
        )
        self.statusBar().showMessage("Connected to backend")
