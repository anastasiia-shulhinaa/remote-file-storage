"""Synchronization sessions: cancellation, journaled remote changes and rollback, concurrency."""

import copy
from datetime import datetime, timedelta, timezone

import pytest

from conftest import make_upload

T0 = datetime(2026, 9, 29, 14, 0, tzinfo=timezone.utc)


def remote_state(backend) -> dict:
    """Everything a sync can change remotely: file rows, folder rows, stored bytes (backups excluded)."""
    return {
        "files": copy.deepcopy(backend.file_repo.rows),
        "folders": copy.deepcopy(backend.folder_repo.rows),
        "objects": {k: v for k, v in backend.storage.objects.items() if "/.sync-backups/" not in k},
    }


def backups(backend) -> list[str]:
    return [k for k in backend.storage.objects if "/.sync-backups/" in k]


@pytest.fixture
def remote(backend, user_id):
    """Remote before the sync: A.txt (OLD), C.txt, labs/keep.c."""
    root = backend.folders.ensure_root(user_id)
    backend.files.upload_file(user_id, root["id"], make_upload("A.txt", b"OLD"), modified_at=T0)
    backend.files.upload_file(user_id, root["id"], make_upload("C.txt", b"remote C"), modified_at=T0)
    backend.files.upload_file(user_id, root["id"], make_upload("keep.c", b"int k;"), relative_dir="labs",
                              modified_at=T0)
    return root


def start(client, root_id, mode="two_way", manifest=None):
    response = client.post("/sync", json={
        "remote_folder_id": root_id,
        "mode": mode,
        "client": "web",
        "manifest": manifest if manifest is not None else [
            {"relative_path": "A.txt", "size": 3, "modified_at": (T0 + timedelta(hours=1)).isoformat()},
            {"relative_path": "B.txt", "size": 1, "modified_at": T0.isoformat()},
        ],
    })
    assert response.status_code == 200, response.text
    return response.json()


def upload(client, sync_id, name, content, relative_dir=None, folder_id=None):
    data = {"synchronization_id": sync_id, "modified_at": (T0 + timedelta(hours=1)).isoformat()}
    if relative_dir:
        data["relative_dir"] = relative_dir
    if folder_id:
        data["folder_id"] = folder_id
    return client.post("/files", data=data, files={"file": (name, content, "text/plain")})


def file_id(backend, name):
    return next(r["id"] for r in backend.file_repo.rows.values() if r["name"] == name)


def cancel_and_rollback(client, sync_id, local_failures=None):
    assert client.post(f"/sync/{sync_id}/cancel").json()["status"] == "CANCEL_REQUESTED"
    rolled = client.post(f"/sync/{sync_id}/rollback")
    assert rolled.status_code == 200, rolled.text
    assert rolled.json()["status"] == "ROLLING_BACK"
    finished = client.post(f"/sync/{sync_id}/rollback/finish", json={
        "local_restored": 0, "local_failures": local_failures or [],
    })
    assert finished.status_code == 200, finished.text
    return finished.json()


# --- the critical acceptance test (remote half) --------------------------------------------------


def test_cancel_restores_remote_state_exactly(client, backend, remote):
    before = remote_state(backend)
    plan = start(client, remote["id"], mode="mirror_local", manifest=[
        {"relative_path": "A.txt", "size": 3, "modified_at": (T0 + timedelta(hours=1)).isoformat()},
        {"relative_path": "new/deep/B.txt", "size": 1, "modified_at": T0.isoformat()},
        {"relative_path": "labs/keep.c", "size": 6, "modified_at": T0.isoformat()},
    ])
    sync_id = plan["synchronization_id"]
    kinds = {c["relative_path"]: c["kind"] for c in plan["changes"]}
    assert kinds == {"A.txt": "UPLOAD_LOCAL", "new/deep/B.txt": "UPLOAD_LOCAL",
                     "C.txt": "DELETE_REMOTE", "labs/keep.c": "UNCHANGED"}

    # execute: overwrite A, create B (and folders new/deep), delete C
    assert upload(client, sync_id, "A.txt", b"NEW").status_code == 201
    assert upload(client, sync_id, "B.txt", b"B", relative_dir="new/deep").status_code == 201
    assert client.delete(f"/files/{file_id(backend, 'C.txt')}", params={"synchronization_id": sync_id}).status_code == 204
    assert remote_state(backend) != before
    assert len(backups(backend)) == 2  # A (overwrite) and C (delete)

    result = cancel_and_rollback(client, sync_id)

    assert result["status"] == "CANCELLED"
    assert remote_state(backend) == before          # rows (all fields, ids, timestamps) + bytes
    assert backups(backend) == []                   # temporary rollback data cleaned
    assert {op["status"] for op in result["operations"]} == {"ROLLED_BACK"}
    assert {op["kind"] for op in result["operations"]} == {
        "OVERWRITE_REMOTE_FILE", "CREATE_REMOTE_FILE", "DELETE_REMOTE_FILE", "CREATE_REMOTE_FOLDER",
    }


def test_cancel_immediately_without_changes(client, backend, remote):
    before = remote_state(backend)
    sync_id = start(client, remote["id"])["synchronization_id"]

    result = cancel_and_rollback(client, sync_id)

    assert result["status"] == "CANCELLED" and result["operations"] == []
    assert remote_state(backend) == before


# --- state machine ----------------------------------------------------------------------------


def test_no_changes_accepted_after_cancel(client, backend, remote):
    sync_id = start(client, remote["id"])["synchronization_id"]
    client.post(f"/sync/{sync_id}/cancel")
    before = remote_state(backend)

    upload_response = upload(client, sync_id, "A.txt", b"LATE")
    delete_response = client.delete(f"/files/{file_id(backend, 'C.txt')}", params={"synchronization_id": sync_id})
    progress = client.patch(f"/synchronizations/{sync_id}", json={"status": "COMPLETED"})

    assert upload_response.status_code == delete_response.status_code == progress.status_code == 409
    assert upload_response.json()["code"] == "sync_cancelled"
    assert progress.json()["code"] == "sync_cancelled"
    assert remote_state(backend) == before


def test_cancel_is_idempotent_and_rollback_runs_once(client, backend, remote):
    sync_id = start(client, remote["id"])["synchronization_id"]
    upload(client, sync_id, "A.txt", b"NEW")
    before_rollback_backups = backups(backend)

    statuses = [client.post(f"/sync/{sync_id}/cancel").json()["status"] for _ in range(3)]
    first = client.post(f"/sync/{sync_id}/rollback").json()
    second = client.post(f"/sync/{sync_id}/rollback").json()   # e.g. a retry after a reconnect

    assert statuses == ["CANCEL_REQUESTED"] * 3
    assert [op["status"] for op in first["operations"]] == ["ROLLED_BACK"]
    assert second["operations"] == first["operations"]
    assert len(before_rollback_backups) == 1 and backups(backend) == []
    assert backend.storage.objects[backend.file_repo.rows[file_id(backend, "A.txt")]["storage_path"]] == b"OLD"


def test_rollback_requires_cancel_and_finished_sync_cannot_be_cancelled(client, remote):
    sync_id = start(client, remote["id"])["synchronization_id"]
    assert client.post(f"/sync/{sync_id}/rollback").json()["code"] == "not_cancelled"
    assert client.post(f"/sync/{sync_id}/rollback/finish", json={}).json()["code"] == "rollback_not_started"

    client.patch(f"/synchronizations/{sync_id}", json={"status": "COMPLETED", "uploaded": 0})

    cancel = client.post(f"/sync/{sync_id}/cancel")
    assert cancel.status_code == 409 and cancel.json()["code"] == "synchronization_finished"


def test_completed_sync_removes_backups_and_commits_journal(client, backend, remote):
    sync_id = start(client, remote["id"])["synchronization_id"]
    upload(client, sync_id, "A.txt", b"NEW")
    assert backups(backend)

    client.patch(f"/synchronizations/{sync_id}", json={"status": "COMPLETED", "uploaded": 1})

    assert backups(backend) == []
    details = client.get(f"/synchronizations/{sync_id}").json()
    assert details["status"] == "COMPLETED"
    assert [op["status"] for op in details["operations"]] == ["COMMITTED"]


def test_half_applied_overwrite_is_restored(client, backend, remote):
    """The DB update fails after the bytes were replaced: the PENDING entry is still reversed."""
    sync_id = start(client, remote["id"])["synchronization_id"]
    before = remote_state(backend)
    original_update = backend.file_repo.update

    def failing_update(*args):
        raise RuntimeError("connection lost")

    backend.file_repo.update = failing_update
    with pytest.raises(RuntimeError):
        upload(client, sync_id, "A.txt", b"NEW")
    backend.file_repo.update = original_update
    assert remote_state(backend) != before          # bytes already overwritten

    result = cancel_and_rollback(client, sync_id)

    assert result["status"] == "CANCELLED"
    assert remote_state(backend) == before


# --- rollback failure ---------------------------------------------------------------------------


def test_rollback_failure_is_reported_and_can_be_retried(client, backend, remote, user_id):
    before = remote_state(backend)
    plan = start(client, remote["id"], mode="mirror_local", manifest=[
        {"relative_path": "A.txt", "size": 3, "modified_at": T0.isoformat()},
        {"relative_path": "labs/keep.c", "size": 6, "modified_at": T0.isoformat()},
    ])
    sync_id = plan["synchronization_id"]
    client.delete(f"/files/{file_id(backend, 'C.txt')}", params={"synchronization_id": sync_id})
    # meanwhile, outside of the sync, a different C.txt appears
    intruder = backend.files.upload_file(user_id, remote["id"], make_upload("C.txt", b"someone else"))

    result = cancel_and_rollback(client, sync_id, local_failures=[
        {"relative_path": "B.txt", "operation": "DELETE_LOCAL_FILE", "code": "local_permission_denied"},
    ])

    assert result["status"] == "ROLLBACK_FAILED"
    report = result["rollback_report"]
    assert report["remote_failures"] == [
        {"relative_path": "C.txt", "operation": "DELETE_REMOTE_FILE", "code": "name_conflict"}]
    assert report["local_failures"][0]["code"] == "local_permission_denied"
    assert len(backups(backend)) == 1               # recovery data kept

    # the conflict is resolved, the rollback is retried
    backend.files.delete_file(user_id, intruder.id)
    retried = client.post(f"/sync/{sync_id}/rollback").json()
    final = client.post(f"/sync/{sync_id}/rollback/finish", json={"local_restored": 1}).json()

    assert retried["operations"][0]["status"] == "ROLLED_BACK"
    assert final["status"] == "CANCELLED"
    assert remote_state(backend) == before


def test_folder_with_foreign_content_is_not_deleted(client, backend, remote, user_id):
    sync_id = start(client, remote["id"])["synchronization_id"]
    upload(client, sync_id, "B.txt", b"B", relative_dir="made")
    made = next(f for f in backend.folder_repo.rows.values() if f["name"] == "made")
    backend.files.upload_file(user_id, made["id"], make_upload("mine.txt", b"keep me"))

    result = cancel_and_rollback(client, sync_id)

    assert result["status"] == "ROLLBACK_FAILED"
    assert result["rollback_report"]["remote_failures"][0]["code"] == "folder_not_empty"
    assert any(r["name"] == "mine.txt" for r in backend.file_repo.rows.values())


def test_changes_outside_the_target_are_rejected(client, backend, remote, user_id):
    labs = next(f for f in backend.folder_repo.rows.values() if f["name"] == "labs")
    plan = start(client, labs["id"], manifest=[
        {"relative_path": "keep.c", "size": 6, "modified_at": (T0 + timedelta(hours=1)).isoformat()},
    ])

    response = upload(client, plan["synchronization_id"], "A.txt", b"NEW", folder_id=remote["id"])

    assert response.status_code == 422 and response.json()["code"] == "outside_sync_target"


# --- concurrency ----------------------------------------------------------------------------------


def test_second_sync_of_the_same_or_overlapping_target_is_rejected(client, backend, remote, user_id):
    labs = next(f for f in backend.folder_repo.rows.values() if f["name"] == "labs")
    sibling = backend.folders.create_folder(user_id, "other", remote["id"])
    sync_id = start(client, remote["id"])["synchronization_id"]

    same = client.post("/sync", json={"remote_folder_id": remote["id"], "manifest": []})
    child = client.post("/sync", json={"remote_folder_id": labs["id"], "manifest": []})

    assert same.status_code == child.status_code == 409
    assert same.json()["code"] == "sync_in_progress"
    assert same.json()["synchronization_id"] == sync_id

    # during the rollback the target stays locked; afterwards it is free again
    client.post(f"/sync/{sync_id}/cancel")
    client.post(f"/sync/{sync_id}/rollback")
    assert client.post("/sync", json={"remote_folder_id": remote["id"], "manifest": []}).status_code == 409
    client.post(f"/sync/{sync_id}/rollback/finish", json={})
    assert client.post("/sync", json={"remote_folder_id": labs["id"], "manifest": []}).status_code == 200
    assert sibling.id  # (unrelated sibling folders are never blocked: covered by the next test)


def test_sibling_folders_can_sync_in_parallel(client, backend, user_id):
    root = backend.folders.ensure_root(user_id)
    one = backend.folders.create_folder(user_id, "one", root["id"])
    two = backend.folders.create_folder(user_id, "two", root["id"])
    manifest = [{"relative_path": "x.c", "size": 1, "modified_at": T0.isoformat()}]

    assert client.post("/sync", json={"remote_folder_id": str(one.id), "manifest": manifest}).status_code == 200
    assert client.post("/sync", json={"remote_folder_id": str(two.id), "manifest": manifest}).status_code == 200


def test_abandoned_running_sync_releases_the_lock(client, backend, remote):
    sync_id = start(client, remote["id"])["synchronization_id"]
    upload(client, sync_id, "A.txt", b"NEW")
    backend.sync_history.rows[sync_id]["updated_at"] = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()

    again = client.post("/sync", json={"remote_folder_id": remote["id"], "manifest": []})

    assert again.status_code == 200
    old = client.get(f"/synchronizations/{sync_id}").json()
    assert (old["status"], old["error"]) == ("FAILED", "interrupted")
    assert backups(backend) == []


def test_history_lists_new_statuses(client, remote):
    sync_id = start(client, remote["id"])["synchronization_id"]
    cancel_and_rollback(client, sync_id)

    [row] = client.get("/synchronizations").json()

    assert row["status"] == "CANCELLED"
    assert row["rollback_report"]["remote_failures"] == []


def test_cancelled_history_keeps_what_was_done_before_the_cancel(client, remote):
    sync_id = start(client, remote["id"])["synchronization_id"]
    upload(client, sync_id, "A.txt", b"NEW")
    client.post(f"/sync/{sync_id}/cancel")
    client.post(f"/sync/{sync_id}/rollback")

    finished = client.post(f"/sync/{sync_id}/rollback/finish", json={
        "local_restored": 0, "counts": {"uploaded": 1, "downloaded": 0},
    }).json()

    assert (finished["status"], finished["uploaded"]) == ("CANCELLED", 1)


# --- folder upload helper ------------------------------------------------------------------------


def test_folder_path_endpoint_creates_nested_folders_idempotently(client, backend, user_id):
    first = client.post("/folders/path", json={"path": "Project/src/utils"})
    second = client.post("/folders/path", json={"path": "Project/src/utils"})

    assert first.status_code == second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    names = sorted(f["name"] for f in backend.folder_repo.rows.values())
    assert names == ["My Drive", "Project", "src", "utils"]
    assert client.post("/folders/path", json={"path": "../evil"}).json()["code"] == "invalid_name"
