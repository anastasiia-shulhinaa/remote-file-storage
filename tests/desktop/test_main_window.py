import httpx
import pytest
from PySide6.QtWidgets import QApplication

from minidrive_desktop.api import ApiClient
from minidrive_desktop.ui.main_window import MainWindow


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def make_window(handler) -> MainWindow:
    client = ApiClient("http://backend.test", transport=httpx.MockTransport(handler))
    return MainWindow(client, "http://backend.test")


def test_main_window_shows_connected_backend(qapp):
    window = make_window(
        lambda request: httpx.Response(
            200,
            json={"status": "ok", "service": "minidrive-backend", "version": "0.1.0", "environment": "test"},
        )
    )

    window.check_backend()

    assert window.windowTitle() == "MiniDrive"
    assert "ok" in window.status_label.text()


def test_main_window_reports_unavailable_backend(qapp):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    window = make_window(handler)

    window.check_backend()

    assert "unavailable" in window.status_label.text()
