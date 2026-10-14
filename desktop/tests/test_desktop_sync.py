import os
from datetime import datetime, timezone

import httpx
import pytest

from app.api_client import ApiClient, ApiError
from app.column_settings import ColumnVisibilitySettings
from app.sync.executor import (
    DELETE_LOCAL,
    DOWNLOAD_REMOTE,
    UNCHANGED,
    UPLOAD_LOCAL,
    SyncExecutor,
    SyncResult,
)
from app.sync.scanner import LocalFolderScanner

T_REMOTE = "2026-09-29T14:00:00+00:00"


class FakeApi:
    def __init__(self):
        self.uploads = []
        self.deleted = []
        self.remote = {"r1": b"remote content"}

    def upload_file(self, path, folder_id=None, relative_dir=None, modified_at=None):
        self.uploads.append((path.name, folder_id, relative_dir, modified_at))
        return {}

    def download_file(self, file_id):
        return self.remote[file_id]

    def delete_file(self, file_id):
        self.deleted.append(file_id)


# --- LocalFolderScanner ------------------------------------------------------------


def test_scanner_builds_manifest_with_posix_paths(tmp_path):
    (tmp_path / "labs").mkdir()
    (tmp_path / "labs" / "lab1.cpp").write_bytes(b"12345")
    (tmp_path / "top.png").write_bytes(b"x")
    os.utime(tmp_path / "top.png", (0, 1_790_000_000))

    manifest = LocalFolderScanner().scan(tmp_path)

    by_path = {m["relative_path"]: m for m in manifest}
    assert set(by_path) == {"labs/lab1.cpp", "top.png"}
    assert by_path["labs/lab1.cpp"]["size"] == 5
    assert by_path["top.png"]["modified_at"] == datetime.fromtimestamp(1_790_000_000, timezone.utc).isoformat()


def test_scanner_rejects_missing_folder(tmp_path):
    with pytest.raises(NotADirectoryError):
        LocalFolderScanner().scan(tmp_path / "missing")


# --- SyncExecutor -------------------------------------------------------------------


def test_executor_runs_every_kind(tmp_path):
    (tmp_path / "labs").mkdir()
    (tmp_path / "labs" / "new.cpp").write_text("new")
    (tmp_path / "old.txt").write_text("old")
    api = FakeApi()
    plan = {"changes": [
        {"relative_path": "labs/new.cpp", "kind": "UPLOAD_LOCAL"},
        {"relative_path": "docs/remote.png", "kind": "DOWNLOAD_REMOTE", "remote_file_id": "r1",
         "remote_modified_at": T_REMOTE},
        {"relative_path": "gone.c", "kind": "DELETE_REMOTE", "remote_file_id": "r2"},
        {"relative_path": "old.txt", "kind": "DELETE_LOCAL"},
        {"relative_path": "same.c", "kind": "UNCHANGED"},
    ]}

    result = SyncExecutor(api, tmp_path, "root-id").execute(plan)

    assert result.errors == []
    assert api.uploads[0][:3] == ("new.cpp", "root-id", "labs")
    downloaded = tmp_path / "docs" / "remote.png"
    assert downloaded.read_bytes() == b"remote content"
    # local mtime = remote modified_at, so the next sync sees UNCHANGED
    assert downloaded.stat().st_mtime == datetime.fromisoformat(T_REMOTE).timestamp()
    assert api.deleted == ["r2"]
    assert not (tmp_path / "old.txt").exists()
    assert "1 uploaded" in result.summary() and "1 unchanged" in result.summary()


def test_executor_refuses_paths_outside_root(tmp_path):
    api = FakeApi()
    plan = {"changes": [{"relative_path": "../evil.txt", "kind": "DOWNLOAD_REMOTE", "remote_file_id": "r1"}]}

    result = SyncExecutor(api, tmp_path / "root", "id").execute(plan)

    assert len(result.errors) == 1
    assert not (tmp_path / "evil.txt").exists()


def test_executor_continues_after_a_failure(tmp_path):
    (tmp_path / "ok.c").write_text("ok")
    api = FakeApi()
    plan = {"changes": [
        {"relative_path": "missing.c", "kind": "UPLOAD_LOCAL"},
        {"relative_path": "ok.c", "kind": "UPLOAD_LOCAL"},
    ]}

    result = SyncExecutor(api, tmp_path, "id").execute(plan)

    assert [e[0] for e in result.errors] == ["missing.c"]
    assert [u[0] for u in api.uploads] == ["ok.c"]


# --- ColumnVisibilitySettings ---------------------------------------------------------


def test_columns_toggle_and_name_always_visible():
    columns = ColumnVisibilitySettings()

    assert columns.toggle_column("created_at") is False
    assert not columns.is_visible("created_at")
    assert columns.is_visible("name")
    with pytest.raises(ValueError):
        columns.toggle_column("name")
    assert ColumnVisibilitySettings.from_dict(columns.to_dict()) == columns


# --- ApiClient ----------------------------------------------------------------------


def make_client(handler) -> ApiClient:
    api = ApiClient("http://test")
    api.client = httpx.Client(base_url="http://test", transport=httpx.MockTransport(handler))
    return api


def session(token: str) -> dict:
    return {"access_token": token, "refresh_token": "refresh-" + token, "user": {"id": "u"}}


def test_api_client_sends_bearer_token_and_refreshes_once():
    calls = []

    def handler(request: httpx.Request):
        calls.append((request.url.path, request.headers.get("authorization")))
        if request.url.path == "/auth/refresh":
            return httpx.Response(200, json=session("new"))
        if request.headers.get("authorization") == "Bearer new":
            return httpx.Response(200, json=[])
        return httpx.Response(401, json={"detail": "Invalid or expired token"})

    api = make_client(handler)
    api._store_session(session("old"))

    assert api.get_files("folder") == []
    assert calls == [("/files", "Bearer old"), ("/auth/refresh", None), ("/files", "Bearer new")]


def test_api_client_raises_api_error_with_detail():
    api = make_client(lambda request: httpx.Response(403, json={"detail": "You do not have access"}))

    with pytest.raises(ApiError) as error:
        api.delete_file("x")
    assert error.value.status_code == 403
    assert "do not have access" in str(error.value)


def test_sync_result_counts_for_history():
    result = SyncResult()
    for kind in (UPLOAD_LOCAL, UPLOAD_LOCAL, DOWNLOAD_REMOTE, DELETE_LOCAL, UNCHANGED):
        result.add(kind)
    result.errors.append(("bad.c", "network error"))

    assert result.history_counts() == {
        "uploaded": 2, "downloaded": 1, "deleted_local": 1,
        "deleted_remote": 0, "unchanged": 1, "failed": 1,
    }
