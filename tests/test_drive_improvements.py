"""Recursive file listing, the JPEG filter, emptying a folder, registration availability
and the stronger password rule."""

import pytest
from fastapi.testclient import TestClient

from app.api import deps
from app.main import app
from app.services.file_service import filter_by_extension
from test_auth import register

# --- files of subfolders ---------------------------------------------------------------


def upload(client, name: str, relative_dir: str | None = None):
    data = {"relative_dir": relative_dir} if relative_dir else {}
    response = client.post("/files", data=data, files={"file": (name, b"x", "application/octet-stream")})
    assert response.status_code == 201, response.text
    return response.json()


def test_recursive_listing_finds_files_of_all_subfolders_with_their_location(client):
    upload(client, "top.c")
    upload(client, "lab1.c", "labs")
    upload(client, "deep.c", "labs/week2")
    upload(client, "photo.jpg", "labs")

    flat = client.get("/files", params={"extension": ".c"}).json()
    assert [f["name"] for f in flat] == ["top.c"]

    everywhere = client.get("/files", params={"extension": ".c", "recursive": "true", "sort": "name", "order": "asc"})
    assert {f["name"]: f["folder_path"] for f in everywhere.json()} == {
        "deep.c": "labs/week2",
        "lab1.c": "labs",
        "top.c": "",
    }


def test_recursive_listing_of_a_subfolder_is_relative_to_it(client):
    labs = upload(client, "lab1.c", "labs")["folder_id"]
    upload(client, "deep.c", "labs/week2")
    upload(client, "outside.c")

    result = client.get("/files", params={"folder_id": labs, "recursive": "true"}).json()
    assert {f["name"]: f["folder_path"] for f in result} == {"lab1.c": "", "deep.c": "week2"}


def test_jpg_filter_finds_every_jpeg_extension():
    files = [{"extension": e} for e in (".jpg", ".jpeg", ".jfif", ".jpe", ".png", ".c")]

    assert [f["extension"] for f in filter_by_extension(files, ".jpg")] == [".jpg", ".jpeg", ".jfif", ".jpe"]
    assert [f["extension"] for f in filter_by_extension(files, ".c")] == [".c"]


# --- emptying a folder -------------------------------------------------------------------


def test_clear_folder_removes_files_and_subfolders_but_keeps_the_folder(client, backend):
    labs = upload(client, "lab1.c", "labs")["folder_id"]
    upload(client, "deep.c", "labs/week2")
    upload(client, "keep.c")

    response = client.delete(f"/folders/{labs}/contents")

    assert response.status_code == 200
    assert response.json() == {"deleted_files": 2, "deleted_folders": 1}
    assert backend.folder_repo.get(labs) is not None                       # the folder stays
    assert client.get("/files", params={"folder_id": labs, "recursive": "true"}).json() == []
    assert [f["name"] for f in client.get("/files").json()] == ["keep.c"]  # nothing else touched
    assert len(backend.storage.objects) == 1                               # bytes removed too


def test_clear_root_folder_is_allowed(client):
    upload(client, "a.c")
    upload(client, "b.c", "labs")
    root = next(f["id"] for f in client.get("/folders").json() if f["parent_folder_id"] is None)

    assert client.delete(f"/folders/{root}/contents").json() == {"deleted_files": 2, "deleted_folders": 1}
    assert [f["name"] for f in client.get("/folders").json()] == ["My Drive"]


def test_clear_folder_of_another_user_is_forbidden(client, backend):
    stranger = backend.add_user("eve@example.com", "Eve")
    eve_root = backend.folders.ensure_root(stranger)

    assert client.delete(f"/folders/{eve_root['id']}/contents").status_code == 403


# --- registration: availability and password rules -------------------------------------------


@pytest.fixture
def api(backend):
    app.dependency_overrides[deps.get_auth_service] = lambda: backend.auth
    app.dependency_overrides[deps.get_folder_service] = lambda: backend.folders
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def test_availability_reports_taken_email_and_username(api):
    assert register(api).status_code == 201

    taken = api.get("/auth/availability", params={"email": " Anna@Example.com ", "username": "ANNA_K"}).json()
    assert taken == {"email": "taken", "username": "taken"}

    free = api.get("/auth/availability", params={"email": "new@example.com", "username": "new_user"}).json()
    assert free == {"email": "available", "username": "available"}

    invalid = api.get("/auth/availability", params={"email": "nope", "username": "a b"}).json()
    assert invalid == {"email": "invalid", "username": "invalid"}


@pytest.mark.parametrize("password, problems", [
    ("secret1!", ["password_needs_uppercase"]),
    ("Secret12", ["password_needs_special"]),
    ("secret12", ["password_needs_uppercase", "password_needs_special"]),
    ("Пароль_1", []),          # Cyrillic capital letter + underscore count too
])
def test_new_passwords_need_a_capital_letter_and_a_special_sign(api, password, problems):
    response = register(api, password=password)
    if problems:
        assert response.status_code == 422
        assert response.json()["problems"] == problems
    else:
        assert response.status_code == 201


def test_existing_weak_passwords_still_log_in(api, backend):
    """The rule applies to new passwords only."""
    backend.auth_gateway.add_account("old@example.com", "secret1")

    response = api.post("/auth/login", json={"identifier": "old@example.com", "password": "secret1"})
    assert response.status_code == 200
