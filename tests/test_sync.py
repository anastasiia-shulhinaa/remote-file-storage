from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.errors import ForbiddenError, ValidationError
from app.schemas.sync import ChangeKind, LocalFileEntry, RemoteFile, SyncMode
from app.synchronization.comparator import FileComparator
from app.synchronization.conflict_resolver import SyncConflictResolver, resolve_conflict
from conftest import make_upload

T0 = datetime(2026, 9, 29, 14, 0, tzinfo=timezone.utc)


def local(path, modified_at=T0, size=10):
    return LocalFileEntry(relative_path=path, size=size, modified_at=modified_at)


def remote(path, modified_at=T0, size=10):
    return RemoteFile(id=uuid4(), relative_path=path, size=size, modified_at=modified_at)


def plan(manifest, remote_files, mode=SyncMode.TWO_WAY):
    entries = FileComparator().compare(manifest, remote_files)
    return {c.relative_path: c.kind for c in SyncConflictResolver().resolve(entries, mode)}


# --- conflict resolution: newer modified_at wins -----------------------------


def test_local_newer_wins():
    local_file = SimpleNamespace(modified_at=20)
    remote_file = SimpleNamespace(modified_at=10)

    result = resolve_conflict(local_file, remote_file)

    assert result == ChangeKind.UPLOAD_LOCAL


def test_remote_newer_wins():
    result = resolve_conflict(local("a.cpp", T0), remote("a.cpp", T0 + timedelta(hours=1)))

    assert result == ChangeKind.DOWNLOAD_REMOTE


def test_equal_timestamp_is_unchanged():
    assert resolve_conflict(local("a.cpp", T0), remote("a.cpp", T0)) == ChangeKind.UNCHANGED


def test_timestamps_within_tolerance_are_equal():
    later = T0 + timedelta(milliseconds=900)

    assert resolve_conflict(local("a.cpp", later), remote("a.cpp", T0)) == ChangeKind.UNCHANGED


def test_demo_conflict_local_15_remote_14():
    """Local modified 15:00, remote 14:00 → newer version wins automatically."""
    result = plan(
        [local("lab1.cpp", T0 + timedelta(hours=1))],
        [remote("lab1.cpp", T0)],
    )

    assert result == {"lab1.cpp": ChangeKind.UPLOAD_LOCAL}


def test_naive_and_aware_timestamps_compare():
    naive_local = local("a.c", datetime(2026, 9, 29, 15, 0))
    assert resolve_conflict(naive_local, remote("a.c", T0)) == ChangeKind.UPLOAD_LOCAL


# --- comparison rules ---------------------------------------------------------


def test_two_way_plan():
    result = plan(
        [local("local_only.cpp"), local("labs/same.c"), local("labs/changed.c", T0 + timedelta(minutes=5))],
        [remote("remote_only.png"), remote("labs/same.c"), remote("labs/changed.c")],
    )

    assert result == {
        "local_only.cpp": ChangeKind.UPLOAD_LOCAL,
        "remote_only.png": ChangeKind.DOWNLOAD_REMOTE,
        "labs/same.c": ChangeKind.UNCHANGED,
        "labs/changed.c": ChangeKind.UPLOAD_LOCAL,
    }


def test_mirror_local_deletes_remote_only_files():
    result = plan([local("a.c")], [remote("a.c"), remote("old.c")], SyncMode.MIRROR_LOCAL)

    assert result == {"a.c": ChangeKind.UNCHANGED, "old.c": ChangeKind.DELETE_REMOTE}


def test_mirror_remote_deletes_local_only_files():
    result = plan([local("a.c"), local("tmp.c")], [remote("a.c")], SyncMode.MIRROR_REMOTE)

    assert result == {"a.c": ChangeKind.UNCHANGED, "tmp.c": ChangeKind.DELETE_LOCAL}


def test_computer_to_storage_overwrites_a_newer_remote_copy():
    """One-way "computer → storage": the storage copy is replaced even when it is newer."""
    newer_remote = T0 + timedelta(hours=1)
    result = plan(
        [local("a.c"), local("b.c", size=99)],
        [remote("a.c", newer_remote), remote("b.c")],
        SyncMode.MIRROR_LOCAL,
    )

    assert result == {"a.c": ChangeKind.UPLOAD_LOCAL, "b.c": ChangeKind.UPLOAD_LOCAL}


def test_storage_to_computer_overwrites_a_newer_local_copy():
    newer_local = T0 + timedelta(hours=1)
    result = plan([local("a.c", newer_local)], [remote("a.c")], SyncMode.MIRROR_REMOTE)

    assert result == {"a.c": ChangeKind.DOWNLOAD_REMOTE}


def test_two_way_still_lets_the_newer_version_win():
    newer_remote = T0 + timedelta(hours=1)
    result = plan([local("a.c")], [remote("a.c", newer_remote)], SyncMode.TWO_WAY)

    assert result == {"a.c": ChangeKind.DOWNLOAD_REMOTE}


def test_windows_paths_are_normalized():
    result = plan([local("labs\\lab1.cpp")], [remote("labs/lab1.cpp")])

    assert result == {"labs/lab1.cpp": ChangeKind.UNCHANGED}


def test_manifest_path_traversal_rejected():
    with pytest.raises(ValidationError):
        FileComparator().compare([local("../outside.txt")], [])


# --- SynchronizationService with remote metadata --------------------------------


def test_sync_service_uses_nested_remote_folders(backend, user_id):
    root = backend.folders.ensure_root(user_id)
    backend.files.upload_file(
        user_id, root["id"], make_upload("lab1.cpp", b"x"), relative_dir="labs", modified_at=T0
    )

    result = backend.sync.run(user_id, root["id"], [local("labs/lab1.cpp", T0 + timedelta(hours=1))])

    [change] = result.changes
    assert change.relative_path == "labs/lab1.cpp"
    assert change.kind == ChangeKind.UPLOAD_LOCAL
    assert change.remote_file_id is not None


def test_sync_foreign_folder_forbidden(backend, user_id):
    stranger = backend.add_user("eve@example.com", "Eve")
    eve_root = backend.folders.ensure_root(stranger)

    with pytest.raises(ForbiddenError):
        backend.sync.run(user_id, eve_root["id"], [])


def test_api_sync(client, backend, user_id):
    root = backend.folders.ensure_root(user_id)
    backend.files.upload_file(user_id, root["id"], make_upload("remote.png", b"x"), modified_at=T0)

    response = client.post("/sync", json={
        "remote_folder_id": root["id"],
        "manifest": [{"relative_path": "lab1.cpp", "size": 1234, "modified_at": "2026-09-29T12:00:00Z"}],
    })

    assert response.status_code == 200
    kinds = {c["relative_path"]: c["kind"] for c in response.json()["changes"]}
    assert kinds == {"lab1.cpp": "UPLOAD_LOCAL", "remote.png": "DOWNLOAD_REMOTE"}
