from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.errors import ForbiddenError, StorageError, ValidationError
from app.core.validation import get_extension, safe_storage_name, split_relative_path, validate_name
from app.main import app
from app.services.file_service import filter_by_extension, sort_files
from conftest import make_upload

# --- filtering ---------------------------------------------------------------


def test_filter_jpg():
    files = [
        {"extension": ".jpg"},
        {"extension": ".cpp"},
    ]

    result = filter_by_extension(files, ".jpg")

    assert len(result) == 1


def test_filter_c_does_not_match_cpp():
    files = [{"extension": ".c"}, {"extension": ".cpp"}, {"extension": ".h"}]

    assert filter_by_extension(files, ".c") == [{"extension": ".c"}]


def test_filter_accepts_extension_without_dot_and_any_case():
    files = [{"extension": ".jpg"}, {"extension": ".png"}]

    assert filter_by_extension(files, "JPG") == [{"extension": ".jpg"}]


def test_empty_filter_returns_everything():
    files = [{"extension": ".jpg"}, {"extension": ".png"}]

    assert filter_by_extension(files, "") == files


# --- sorting -----------------------------------------------------------------


def test_sort_created_at():
    files = [
        {"created_at": 3},
        {"created_at": 1},
        {"created_at": 2},
    ]

    result = sort_files(files, "created_at", "asc")

    assert [x["created_at"] for x in result] == [1, 2, 3]


def test_sort_created_at_desc_with_iso_strings():
    files = [
        {"name": "a", "created_at": "2026-09-01T10:00:00+00:00"},
        {"name": "b", "created_at": "2026-09-03T10:00:00+00:00"},
        {"name": "c", "created_at": "2026-09-02T10:00:00Z"},
    ]

    result = sort_files(files, "created_at", "desc")

    assert [x["name"] for x in result] == ["b", "c", "a"]


def test_sort_rejects_unknown_field():
    with pytest.raises(ValidationError):
        sort_files([], "storage_path", "asc")


# --- validation --------------------------------------------------------------


@pytest.mark.parametrize("name", ["", "   ", "a/b.txt", "a\\b.txt", "..", "bad:name"])
def test_invalid_file_names_rejected(name):
    with pytest.raises(ValidationError):
        validate_name(name)


@pytest.mark.parametrize("path", ["../secret.txt", "/etc/passwd", "C:/Windows/x.txt", "a/../../b"])
def test_path_traversal_rejected(path):
    with pytest.raises(ValidationError):
        split_relative_path(path)


def test_extensions():
    assert get_extension("Main.CPP") == ".cpp"
    assert get_extension("photo.jpg") == ".jpg"
    assert get_extension("Makefile") == ""
    assert get_extension(".gitignore") == ""


def test_storage_name_is_ascii_safe():
    assert safe_storage_name("Лабораторна 1.cpp") == "1.cpp"
    assert safe_storage_name("звіт.txt") == "txt"
    assert safe_storage_name("my report (v2).cpp") == "my_report_v2_.cpp"


# --- FileService ---------------------------------------------------------------


def test_upload_stores_metadata_and_content(backend, user_id):
    dto = backend.files.upload_file(user_id, None, make_upload("lab1.cpp", b"int main(){}"))

    assert dto.name == "lab1.cpp"
    assert dto.extension == ".cpp"
    assert dto.size == 12
    assert dto.uploaded_by == user_id
    assert dto.uploaded_by_name == "Anna"
    assert dto.storage_path.startswith(f"{user_id}/")
    assert backend.storage.objects[dto.storage_path] == b"int main(){}"


def test_upload_same_name_replaces_file(backend, user_id):
    first = backend.files.upload_file(user_id, None, make_upload("a.cpp", b"v1"))
    second = backend.files.upload_file(user_id, None, make_upload("a.cpp", b"version 2"))

    assert first.id == second.id
    assert second.size == 9
    assert len(backend.file_repo.rows) == 1
    assert backend.storage.objects[second.storage_path] == b"version 2"


def test_upload_into_relative_dir_creates_folders(backend, user_id):
    dto = backend.files.upload_file(user_id, None, make_upload("x.c", b"x"), relative_dir="labs/lab1")

    folder = backend.folder_repo.get(dto.folder_id)
    assert folder["name"] == "lab1"
    assert backend.folder_repo.get(folder["parent_folder_id"])["name"] == "labs"


def test_upload_keeps_given_modified_at(backend, user_id):
    moment = datetime(2026, 9, 29, 12, 30, tzinfo=timezone.utc)
    dto = backend.files.upload_file(user_id, None, make_upload("a.c", b"a"), modified_at=moment)

    assert dto.modified_at == moment


def test_upload_too_large_rejected(backend, user_id, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "max_file_size", 10)
    with pytest.raises(ValidationError):
        backend.files.upload_file(user_id, None, make_upload("big.bin", b"x" * 11))
    assert backend.storage.objects == {}


def test_cannot_access_other_users_file(backend, user_id):
    stranger = backend.add_user("eve@example.com", "Eve")
    dto = backend.files.upload_file(user_id, None, make_upload("secret.cpp", b"secret"))

    with pytest.raises(ForbiddenError):
        backend.files.download_file(stranger, dto.id)
    with pytest.raises(ForbiddenError):
        backend.files.delete_file(stranger, dto.id)


def test_cannot_upload_into_other_users_folder(backend, user_id):
    stranger = backend.add_user("eve@example.com", "Eve")
    eve_root = backend.folders.ensure_root(stranger)

    with pytest.raises(ForbiddenError):
        backend.files.upload_file(user_id, eve_root["id"], make_upload("a.c", b"a"))


def test_delete_keeps_metadata_when_storage_fails(backend, user_id):
    dto = backend.files.upload_file(user_id, None, make_upload("a.c", b"a"))
    backend.storage.fail_delete = True

    with pytest.raises(StorageError):
        backend.files.delete_file(user_id, dto.id)
    assert backend.file_repo.get_by_id(dto.id) is not None


def test_delete_folder_removes_nested_files_from_storage(backend, user_id):
    backend.files.upload_file(user_id, None, make_upload("a.c", b"a"), relative_dir="labs/deep")
    labs = backend.folder_repo.find_child(user_id, backend.folders.ensure_root(user_id)["id"], "labs")

    backend.folders.delete_folder(user_id, labs["id"])

    assert backend.storage.objects == {}
    assert backend.file_repo.rows == {}


# --- REST API ------------------------------------------------------------------


def test_health():
    from app.api import deps

    app.dependency_overrides[deps.get_schema_check] = lambda: (lambda force=False: ["003_sync_rollback.sql"])
    try:
        with TestClient(app) as client:
            assert client.get("/health").json() == {
                "status": "ok", "database": "migration_required", "missing_migrations": ["003_sync_rollback.sql"],
            }
    finally:
        app.dependency_overrides.clear()


def test_missing_token_returns_401():
    with TestClient(app) as client:
        assert client.get("/files").status_code == 401


def test_invalid_token_returns_401():
    with TestClient(app) as client:
        response = client.get("/files", headers={"Authorization": "Bearer not-a-jwt"})
    assert response.status_code == 401


def test_api_upload_list_download_delete(client):
    response = client.post("/files", files={"file": ("lab1.cpp", b"int main(){}", "text/plain")})
    assert response.status_code == 201
    file_id = response.json()["id"]

    listing = client.get("/files").json()
    assert [f["name"] for f in listing] == ["lab1.cpp"]

    content = client.get(f"/files/{file_id}/content")
    assert content.status_code == 200
    assert content.content == b"int main(){}"
    assert "lab1.cpp" in content.headers["content-disposition"]

    assert client.delete(f"/files/{file_id}").status_code == 204
    assert client.get(f"/files/{file_id}").status_code == 404


def test_api_filter_and_sort(client, backend, user_id):
    base = datetime(2026, 9, 1, tzinfo=timezone.utc)
    for i, name in enumerate(["b.jpg", "a.cpp", "c.jpg"]):
        client.post("/files", files={"file": (name, b"x", "application/octet-stream")})
        row = next(r for r in backend.file_repo.rows.values() if r["name"] == name)
        row["created_at"] = (base + timedelta(days=i)).isoformat()

    jpg = client.get("/files", params={"extension": ".jpg", "sort": "created_at", "order": "asc"}).json()
    assert [f["name"] for f in jpg] == ["b.jpg", "c.jpg"]

    desc = client.get("/files", params={"sort": "created_at", "order": "desc"}).json()
    assert [f["name"] for f in desc] == ["c.jpg", "a.cpp", "b.jpg"]

    assert client.get("/files", params={"sort": "size; drop table"}).status_code == 422


def test_api_upload_invalid_name_returns_422(client):
    response = client.post("/files", files={"file": ("..", b"x", "text/plain")})
    assert response.status_code == 422


def test_api_unknown_file_returns_404(client):
    assert client.get(f"/files/{uuid4()}").status_code == 404


def test_api_folders(client):
    root = client.get("/folders").json()
    assert [f["name"] for f in root] == ["My Drive"]

    created = client.post("/folders", json={"name": "labs"})
    assert created.status_code == 201
    assert client.post("/folders", json={"name": "labs"}).status_code == 409

    folder_id = created.json()["id"]
    details = client.get(f"/folders/{folder_id}").json()
    assert details["name"] == "labs" and details["files"] == []

    assert client.delete(f"/folders/{root[0]['id']}").status_code == 400
    assert client.delete(f"/folders/{folder_id}").status_code == 204
