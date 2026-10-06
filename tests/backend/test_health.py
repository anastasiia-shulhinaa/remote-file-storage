from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def make_client(**settings_overrides) -> TestClient:
    settings = Settings(_env_file=None, **settings_overrides)
    return TestClient(create_app(settings))


def test_health_returns_ok():
    response = make_client(app_env="test").get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "minidrive-backend"
    assert body["environment"] == "test"


def test_cors_allows_configured_origin_only():
    client = make_client(cors_origins="http://localhost:5173")

    allowed = client.get("/health", headers={"Origin": "http://localhost:5173"})
    denied = client.get("/health", headers={"Origin": "http://evil.example"})

    assert allowed.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert "access-control-allow-origin" not in denied.headers


def test_settings_parse_comma_separated_cors_origins():
    settings = Settings(_env_file=None, cors_origins="http://a.test, http://b.test ,")

    assert settings.cors_origin_list == ["http://a.test", "http://b.test"]


def test_settings_secrets_are_not_exposed_in_repr():
    settings = Settings(_env_file=None, supabase_service_role_key="super-secret")

    assert "super-secret" not in repr(settings)
