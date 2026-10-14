"""Desktop ↔ real backend (fakes for Supabase): cancellation with rollback, recovery, folder upload.

The critical acceptance test: LOCAL_AFTER == LOCAL_BEFORE (bytes + modification times)
and REMOTE_AFTER == REMOTE_BEFORE (all metadata + bytes) after cancel + rollback.
"""

import importlib.util
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from app.api_client import ApiClient
from app.folder_upload import collect_paths, upload_selection
from app.sync.executor import SyncExecutor
from app.sync.journal import LocalJournal
from app.sync.scanner import LocalFolderScanner
from app.sync.session import cancel_and_rollback, pending_recoveries

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("fastapi") is None or importlib.util.find_spec("supabase") is None,
    reason="backend dependencies are not installed in this environment",
)

PAST = 1_767_261_600      # 2026-01-01 10:00 UTC
FUTURE = 1_893_492_000    # 2030-01-01 10:00 UTC
SERVER = Path(__file__).parent / "support" / "backend_server.py"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def server():
    port = free_port()
    process = subprocess.Popen([sys.executable, str(SERVER), str(port)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            if httpx.get(url + "/health").status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.1)
    else:
        process.kill()
        pytest.fail("backend did not start")
    yield url
    process.kill()
    process.wait()


@pytest.fixture
def api(server) -> ApiClient:
    client = ApiClient(server)
    client.login("anna", "secret1")
    return client


@pytest.fixture
def journals(tmp_path, monkeypatch):
    root = tmp_path / "journals"
    monkeypatch.setenv("MINIDRIVE_JOURNAL_DIR", str(root))
    return root


def root_id(api) -> str:
    return next(f["id"] for f in api.get_folders() if not f["parent_folder_id"])


def remote_state(api) -> dict:
    state = api.client.post("/__test__/remote-state").json()
    return {k: state[k] for k in ("files", "folders", "objects")}


def local_state(folder: Path) -> dict:
    """Relative path → (bytes, mtime) for files, plus the directory set."""
    files, dirs = {}, set()
    for path in folder.rglob("*"):
        rel = path.relative_to(folder).as_posix()
        if path.is_dir():
            dirs.add(rel)
        else:
            files[rel] = (path.read_bytes(), path.stat().st_mtime)
    return {"files": files, "dirs": dirs}


def write(path: Path, content: bytes, mtime: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    os.utime(path, (mtime, mtime))


def upload_remote(api, tmp_path, name: str, content: bytes, mtime_iso: str, relative_dir=None):
    source = tmp_path / "staging" / name
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(content)
    api.upload_file(source, folder_id=root_id(api), relative_dir=relative_dir, modified_at=mtime_iso)


def run_until(api, local: Path, mode: str, stop_after: int | None):
    """Plan + execute; stop (cancel) after `stop_after` completed changes. Returns (plan, journal, result)."""
    plan = api.post_sync(root_id(api), LocalFolderScanner().scan(local), mode)
    journal = LocalJournal.create(plan["synchronization_id"], plan["remote_folder_id"], local)
    done = []
    executor = SyncExecutor(
        api, local, plan["remote_folder_id"], plan["synchronization_id"], journal,
        should_stop=lambda: stop_after is not None and len(done) >= stop_after,
    )
    result = executor.execute(plan, on_progress=lambda i, change, error: done.append(i)
                              if change["kind"] != "UNCHANGED" else None)
    return plan, journal, result


@pytest.fixture
def scenario(api, tmp_path, journals):
    """Local: A (newer), D (older), loc/B (local only). Remote: A (older), D (newer), rem/C (remote only)."""
    local = tmp_path / "local"
    write(local / "A.txt", b"LOCAL NEW A", PAST + 7200)
    write(local / "D.txt", b"LOCAL OLD D", PAST)
    write(local / "loc" / "B.txt", b"LOCAL B", PAST)
    upload_remote(api, tmp_path, "A.txt", b"REMOTE OLD A", "2026-01-01T10:00:00+00:00")
    upload_remote(api, tmp_path, "D.txt", b"REMOTE NEW D", "2030-01-01T10:00:00+00:00")
    upload_remote(api, tmp_path, "C.txt", b"REMOTE C", "2026-01-01T10:00:00+00:00", relative_dir="rem")
    return local


# --- the critical acceptance test -------------------------------------------------------------


@pytest.mark.parametrize("stop_after", [0, 1, 2, 3])
def test_cancel_restores_local_and_remote_exactly(api, scenario, stop_after):
    """0 = immediately, 1 = after the upload (overwrite), 2 = after a download (overwrite), 3 = near the end."""
    local_before, remote_before = local_state(scenario), remote_state(api)

    plan, journal, result = run_until(api, scenario, "two_way", stop_after)
    assert result.stopped
    assert [c["kind"] for c in plan["changes"]] == ["UPLOAD_LOCAL", "DOWNLOAD_REMOTE", "UPLOAD_LOCAL", "DOWNLOAD_REMOTE"]

    outcome = cancel_and_rollback(api, plan["synchronization_id"], journal)

    assert outcome.status == "CANCELLED", outcome.failures
    assert local_state(scenario) == local_before          # bytes AND modification times
    assert remote_state(api) == remote_before             # every metadata field AND bytes
    assert not journal.directory.exists()                 # temporary rollback data removed
    assert api.client.post("/__test__/remote-state").json()["backups"] == []
    assert api.get_synchronizations()[0]["status"] == "CANCELLED"


def test_cancel_during_deletions_restores_files(api, scenario):
    write(scenario / "x1.txt", b"X1", PAST)
    write(scenario / "x2.txt", b"X2", PAST)
    local_before, remote_before = local_state(scenario), remote_state(api)

    plan, journal, result = run_until(api, scenario, "mirror_remote", stop_after=3)
    kinds = [c["kind"] for c in plan["changes"] if c["kind"] != "UNCHANGED"]
    assert "DELETE_LOCAL" in kinds
    outcome = cancel_and_rollback(api, plan["synchronization_id"], journal)

    assert outcome.status == "CANCELLED"
    assert local_state(scenario) == local_before
    assert remote_state(api) == remote_before


def test_cancel_during_remote_deletions_restores_files(api, scenario):
    local_before, remote_before = local_state(scenario), remote_state(api)

    plan, journal, result = run_until(api, scenario, "mirror_local", stop_after=3)
    assert any(c["kind"] == "DELETE_REMOTE" for c in plan["changes"])
    outcome = cancel_and_rollback(api, plan["synchronization_id"], journal)

    assert outcome.status == "CANCELLED"
    assert local_state(scenario) == local_before
    assert remote_state(api) == remote_before


def test_completed_sync_cleans_journal(api, scenario):
    plan, journal, result = run_until(api, scenario, "two_way", stop_after=None)
    api.report_synchronization(plan["synchronization_id"], "COMPLETED", result.history_counts())
    journal.discard()

    assert not result.stopped and result.errors == []
    assert api.get_synchronizations()[0]["status"] == "COMPLETED"
    assert api.client.post("/__test__/remote-state").json()["backups"] == []
    assert (scenario / "rem" / "C.txt").read_bytes() == b"REMOTE C"


# --- crash / restart: rollback resumed from the persisted journal -------------------------------


def test_interrupted_sync_is_recovered_after_restart(api, scenario, journals):
    local_before, remote_before = local_state(scenario), remote_state(api)
    plan, journal, result = run_until(api, scenario, "two_way", stop_after=2)
    del journal  # the application "crashed": nothing in memory survives

    [(stored, status)] = pending_recoveries(api)
    assert status == "RUNNING" and stored.data.synchronization_id == plan["synchronization_id"]
    outcome = cancel_and_rollback(api, plan["synchronization_id"], stored)

    assert outcome.status == "CANCELLED"
    assert local_state(scenario) == local_before
    assert remote_state(api) == remote_before
    assert pending_recoveries(api) == []


def test_second_sync_of_the_same_folder_is_refused_while_running(api, scenario):
    plan, journal, result = run_until(api, scenario, "two_way", stop_after=1)

    with pytest.raises(Exception) as blocked:
        api.post_sync(root_id(api), [], "two_way")
    assert getattr(blocked.value, "code", None) == "sync_in_progress"

    cancel_and_rollback(api, plan["synchronization_id"], journal)
    assert api.post_sync(root_id(api), [], "two_way")["changes"]  # free again


def test_local_rollback_failure_is_reported(api, scenario):
    plan, journal, result = run_until(api, scenario, "two_way", stop_after=None)
    # the user put something into the folder the sync created
    (scenario / "rem" / "mine.txt").write_bytes(b"keep me")

    outcome = cancel_and_rollback(api, plan["synchronization_id"], journal)

    assert outcome.status == "ROLLBACK_FAILED"
    assert {"relative_path": "rem", "operation": "CREATE_LOCAL_FOLDER", "code": "folder_not_empty", "side": "local"} \
        in outcome.failures
    assert (scenario / "rem" / "mine.txt").read_bytes() == b"keep me"
    assert journal.directory.exists()  # recovery information kept
    assert api.get_synchronizations()[0]["status"] == "ROLLBACK_FAILED"


# --- folder drag-and-drop upload ------------------------------------------------------------------


def test_folder_upload_preserves_structure_and_reports_failures(api, tmp_path):
    project = tmp_path / "drop" / "Project"
    write(project / "src" / "main.py", b"print('main')", PAST)
    write(project / "src" / "utils.py", b"def u(): pass", PAST)
    write(project / "docs" / "README.pdf", b"%PDF-1.4", PAST)
    write(project / "image.png", b"png", PAST)
    (project / "empty").mkdir()
    with (project / "big.bin").open("wb") as big:
        big.truncate(51 * 1024 * 1024)

    selection = collect_paths([project])
    outcome = upload_selection(api, selection, root_id(api))

    assert outcome.uploaded == 4 and outcome.folders_created == 1
    assert [(path, getattr(exc, "code", None)) for path, exc in outcome.failures] == [("Project/big.bin", "file_too_large")]
    folders = {f["id"]: f for f in api.get_folders()}
    by_name = {f["name"]: f for f in folders.values()}
    assert folders[by_name["src"]["parent_folder_id"]]["name"] == "Project"
    assert sorted(f["name"] for f in api.get_files(by_name["src"]["id"])) == ["main.py", "utils.py"]
    assert [f["name"] for f in api.get_files(by_name["Project"]["id"])] == ["image.png"]
    assert api.get_files(by_name["empty"]["id"]) == []

    # dropping the same folder again overwrites instead of duplicating
    again = upload_selection(api, collect_paths([project]), root_id(api))
    assert again.uploaded == 4
    assert sorted(f["name"] for f in api.get_files(by_name["src"]["id"])) == ["main.py", "utils.py"]
