import io

import pytest
from fastapi.testclient import TestClient
from starlette.datastructures import Headers, UploadFile

from app.api import deps
from app.core.security import CurrentUser, get_current_user
from app.main import app
from fakes import FakeBackend


@pytest.fixture
def backend() -> FakeBackend:
    return FakeBackend()


@pytest.fixture
def user_id(backend):
    return backend.add_user()


@pytest.fixture
def client(backend, user_id):
    """TestClient authenticated as user_id, with Supabase replaced by fakes."""
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id=user_id, email="anna@example.com", access_token="test-token"
    )
    app.dependency_overrides[deps.get_folder_service] = lambda: backend.folders
    app.dependency_overrides[deps.get_file_service] = lambda: backend.files
    app.dependency_overrides[deps.get_auth_service] = lambda: backend.auth
    app.dependency_overrides[deps.get_sync_service] = lambda: backend.sync
    app.dependency_overrides[deps.get_settings_service] = lambda: backend.settings
    app.dependency_overrides[deps.get_schema_check] = lambda: (lambda force=False: [])
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def make_upload(name: str, content: bytes, content_type: str = "application/octet-stream") -> UploadFile:
    return UploadFile(
        file=io.BytesIO(content),
        filename=name,
        headers=Headers({"content-type": content_type}),
    )
