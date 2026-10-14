"""SyncPage UI ↔ real backend (fakes for Supabase): a stopped synchronization must not
block the next one of the same folder."""

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.sync import sync_page as sync_page_module
from app.sync.sync_page import SyncPage
from test_sync_cancel_integration import api, journals, root_id, scenario, server  # noqa: F401  (fixtures)

pytestmark = sync_page_module and pytest.mark.usefixtures("journals")


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


def wait_until(condition, timeout=20.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        QTest.qWait(30)
        if condition():
            return True
    return False


def make_page(api, local, mode: str) -> SyncPage:
    page = SyncPage(api, toast=lambda *a, **k: None)
    page.set_folders(api.get_folders(), root_id(api))
    page.local_edit.setText(str(local))
    for radio in page.mode_group.buttons():
        radio.setChecked(radio.property("mode") == mode)
    return page


def history_statuses(api) -> list[str]:
    return [h["status"] for h in api.get_synchronizations(10)]


def test_declined_deletions_cancel_the_session_and_allow_a_new_sync(qt_app, api, scenario, monkeypatch):
    answers = iter([False, True])  # 1st run: decline the deletions, 2nd run: accept
    monkeypatch.setattr(sync_page_module, "confirm", lambda *a, **k: next(answers))
    page = make_page(api, scenario, "mirror_remote")  # local-only loc/B.txt → DELETE_LOCAL

    page.start()
    assert wait_until(lambda: page.phase in ("cancelled", "rollback_failed")), page.phase
    assert page.phase == "cancelled"
    assert page.start_button.isEnabled()
    assert history_statuses(api)[0] == "CANCELLED"  # the server session no longer locks the folder
    assert (scenario / "loc" / "B.txt").exists()     # nothing was executed

    page.start()
    assert wait_until(lambda: page.phase == "done"), page.phase
    assert history_statuses(api)[0] == "COMPLETED"
    assert not (scenario / "loc" / "B.txt").exists()


def test_sync_cancelled_while_running_can_be_started_again(qt_app, api, scenario, monkeypatch):
    monkeypatch.setattr(sync_page_module, "confirm", lambda *a, **k: True)
    page = make_page(api, scenario, "two_way")

    page.start()
    assert wait_until(lambda: page.phase == "running")
    page.cancel()
    assert wait_until(lambda: page.phase in ("cancelled", "rollback_failed")), page.phase
    assert page.phase == "cancelled"

    page.start()
    assert wait_until(lambda: page.phase == "done"), page.phase
    assert history_statuses(api)[0] == "COMPLETED"
