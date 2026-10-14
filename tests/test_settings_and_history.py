from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.core.config import settings
from app.schemas.sync import LocalFileEntry
from conftest import make_upload

T0 = datetime(2026, 9, 29, 14, 0, tzinfo=timezone.utc)


# --- column visibility settings ------------------------------------------------


def test_columns_default_to_visible(client):
    response = client.get("/settings/columns")

    assert response.status_code == 200
    assert response.json() == {
        "size": True, "created_at": True, "modified_at": True, "uploaded_by": True, "modified_by": True,
    }


def test_columns_patch_persists_per_user(client, backend, user_id):
    response = client.patch("/settings/columns", json={"uploaded_by": False, "size": False})

    assert response.status_code == 200
    assert response.json()["uploaded_by"] is False
    assert client.get("/settings/columns").json()["size"] is False
    # another user keeps the defaults
    stranger = backend.add_user("eve@example.com", "Eve")
    assert backend.settings.get(stranger).uploaded_by is True


def test_name_column_cannot_be_hidden(client):
    response = client.patch("/settings/columns", json={"name": False})

    assert response.status_code == 422


# --- synchronization history ------------------------------------------------------


def _sync(client, root_id, manifest):
    return client.post("/sync", json={"remote_folder_id": root_id, "manifest": manifest, "client": "web"})


def test_sync_creates_pending_history_record(client, backend, user_id):
    root = backend.folders.ensure_root(user_id)

    plan = _sync(client, root["id"], [
        {"relative_path": "lab1.cpp", "size": 3, "modified_at": "2026-09-29T12:00:00Z"},
    ]).json()

    assert plan["synchronization_id"] is not None
    [record] = client.get("/synchronizations").json()
    assert record["id"] == plan["synchronization_id"]
    assert record["status"] == "PENDING"
    assert record["client"] == "web"
    assert record["planned_changes"] == 1


def test_sync_with_nothing_to_do_is_completed_immediately(client, backend, user_id):
    root = backend.folders.ensure_root(user_id)
    backend.files.upload_file(user_id, root["id"], make_upload("a.c", b"x"), modified_at=T0)

    plan = _sync(client, root["id"], [
        {"relative_path": "a.c", "size": 1, "modified_at": T0.isoformat()},
    ]).json()

    assert [c["kind"] for c in plan["changes"]] == ["UNCHANGED"]
    [record] = client.get("/synchronizations").json()
    assert record["status"] == "COMPLETED"
    assert record["unchanged"] == 1
    assert record["finished_at"] is not None


def test_report_lifecycle_running_then_failed(client, backend, user_id):
    root = backend.folders.ensure_root(user_id)
    sync_id = _sync(client, root["id"], [
        {"relative_path": "a.c", "size": 1, "modified_at": T0.isoformat()},
        {"relative_path": "b.c", "size": 1, "modified_at": T0.isoformat()},
    ]).json()["synchronization_id"]

    running = client.patch(f"/synchronizations/{sync_id}", json={"status": "RUNNING"})
    assert running.status_code == 200 and running.json()["finished_at"] is None

    failed = client.patch(f"/synchronizations/{sync_id}", json={
        "status": "FAILED", "uploaded": 1, "failed": 1, "error": "b.c: network error",
    })
    assert failed.status_code == 200
    body = failed.json()
    assert (body["status"], body["uploaded"], body["failed"]) == ("FAILED", 1, 1)
    assert body["finished_at"] is not None

    # a finished synchronization cannot be changed or "fixed" into a success
    again = client.patch(f"/synchronizations/{sync_id}", json={"status": "COMPLETED", "uploaded": 2})
    assert again.status_code == 409


def test_cannot_report_foreign_synchronization(client, backend, user_id):
    stranger = backend.add_user("eve@example.com", "Eve")
    eve_root = backend.folders.ensure_root(stranger)
    plan = backend.sync.run(stranger, eve_root["id"], [
        LocalFileEntry(relative_path="x.c", size=1, modified_at=T0),
    ])

    response = client.patch(f"/synchronizations/{plan.synchronization_id}", json={"status": "COMPLETED"})

    assert response.status_code == 403
    assert client.get("/synchronizations").json() == []


def test_history_failure_refuses_sync_with_clear_code(client, backend, user_id):
    """Without a session the run could not be cancelled: refuse instead of degrading silently."""
    backend.sync_history.fail_create = True
    root = backend.folders.ensure_root(user_id)

    response = _sync(client, root["id"], [
        {"relative_path": "a.c", "size": 1, "modified_at": T0.isoformat()},
    ])

    assert response.status_code == 503
    assert response.json()["code"] == "schema_outdated"   # the fake error says "does not exist"


def test_outdated_schema_on_lock_check_is_a_clear_503_not_a_500(client, backend, user_id):
    root = backend.folders.ensure_root(user_id)

    def missing_column(*_):
        raise RuntimeError("{'message': 'column synchronizations.updated_at does not exist', 'code': '42703'}")

    backend.sync_history.list_with_status = missing_column

    response = _sync(client, root["id"], [])

    assert response.status_code == 503 and response.json()["code"] == "schema_outdated"


def test_device_is_stored_and_returned(client, backend, user_id):
    root = backend.folders.ensure_root(user_id)
    plan = client.post("/sync", json={
        "remote_folder_id": root["id"], "client": "desktop", "device": "LAB-PC-07\n",
        "manifest": [{"relative_path": "a.c", "size": 1, "modified_at": T0.isoformat()}],
    }).json()

    details = client.get(f"/synchronizations/{plan['synchronization_id']}").json()

    assert (details["client"], details["device"]) == ("desktop", "LAB-PC-07")
    assert client.get("/synchronizations").json()[0]["device"] == "LAB-PC-07"


def test_health_reports_database_state(client):
    body = client.get("/health").json()

    assert body["status"] == "ok" and "database" in body


# --- web client hosting -------------------------------------------------------------


def test_built_web_client_is_served_without_shadowing_api(tmp_path, monkeypatch):
    import importlib

    import app.main as main_module

    (tmp_path / "index.html").write_text("<div id=root></div>", encoding="utf-8")
    (tmp_path / "worker.mjs").write_text("export {};", encoding="utf-8")
    monkeypatch.setattr(settings, "web_dist_dir", tmp_path)
    reloaded = importlib.reload(main_module)
    from app.api import deps

    reloaded.app.dependency_overrides[deps.get_schema_check] = lambda: (lambda force=False: [])
    try:
        with TestClient(reloaded.app) as browser:
            assert "id=root" in browser.get("/").text
            assert browser.get("/health").json()["status"] == "ok"
            assert browser.get("/files").status_code == 401
            # module workers are only executed when served as JavaScript
            assert "javascript" in browser.get("/worker.mjs").headers["content-type"]
    finally:
        monkeypatch.undo()
        importlib.reload(main_module)


# --- missing tables (supabase/schema.sql not applied): clear 503 codes, no raw errors ------------


class _MissingTable:
    def __getattr__(self, name):
        def fail(*args, **kwargs):
            raise RuntimeError("Could not find the table 'public.synchronizations' in the schema cache")
        return fail


def test_history_without_table_is_503_with_code(client, backend):
    backend.sync.history = _MissingTable()

    response = client.get("/synchronizations")

    assert response.status_code == 503
    # the table is missing: the precise cause is reported (and logged with the migration to run)
    assert response.json() == {"detail": "Database schema is outdated", "code": "schema_outdated"}


def test_columns_without_table_is_503_with_code(client, backend):
    backend.settings.repository = _MissingTable()

    assert client.get("/settings/columns").json()["code"] == "settings_unavailable"
    assert client.patch("/settings/columns", json={"size": False}).status_code == 503


def test_empty_history_is_an_empty_list(client):
    assert client.get("/synchronizations").json() == []
