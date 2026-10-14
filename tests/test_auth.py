"""Login by email or username, reliable "user not found", error codes without raw Supabase text."""

import pytest
from fastapi.testclient import TestClient

from app.api import deps
from app.main import app


@pytest.fixture
def api(backend):
    """Unauthenticated client: real AuthService, Supabase Auth replaced by FakeAuthGateway."""
    app.dependency_overrides[deps.get_auth_service] = lambda: backend.auth
    app.dependency_overrides[deps.get_folder_service] = lambda: backend.folders
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def register(api, email="anna@example.com", username="anna_k", password="Secret1!"):
    return api.post("/auth/register", json={
        "email": email, "password": password, "display_name": "Anna", "username": username,
    })


def test_register_stores_username_and_logs_in(api, backend):
    response = register(api)

    assert response.status_code == 201
    session = response.json()["session"]
    assert session["user"]["username"] == "anna_k"
    assert backend.users.get_by_username("anna_k")["email"] == "anna@example.com"


def test_username_is_case_insensitive_and_validated(api):
    assert register(api, username="Anna_K").json()["session"]["user"]["username"] == "anna_k"
    assert register(api, email="b@example.com", username="a@b").status_code == 422
    assert register(api, email="c@example.com", username="xy").status_code == 422


def test_username_taken(api):
    register(api)

    response = register(api, email="other@example.com", username="anna_k")

    assert response.status_code == 409
    assert response.json()["code"] == "username_taken"


def test_existing_email_is_conflict(api):
    register(api)

    response = register(api, username="someone_else")

    assert response.status_code == 409
    assert response.json()["code"] == "user_exists"


def test_login_with_email(api):
    register(api)

    response = api.post("/auth/login", json={"identifier": "Anna@Example.com", "password": "Secret1!"})

    assert response.status_code == 200
    assert response.json()["user"]["email"] == "anna@example.com"


def test_login_with_username(api):
    register(api)

    response = api.post("/auth/login", json={"identifier": "ANNA_K", "password": "Secret1!"})

    assert response.status_code == 200
    assert response.json()["user"]["username"] == "anna_k"


def test_legacy_email_field_still_works(api):
    """The desktop client sends {"email", "password"}."""
    register(api)

    response = api.post("/auth/login", json={"email": "anna@example.com", "password": "Secret1!"})

    assert response.status_code == 200


@pytest.mark.parametrize("identifier", ["anna@example.com", "anna_k"])
def test_wrong_password_is_invalid_credentials(api, identifier):
    register(api)

    response = api.post("/auth/login", json={"identifier": identifier, "password": "nope"})

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid login credentials", "code": "invalid_credentials"}


@pytest.mark.parametrize("identifier", ["ghost@example.com", "ghost_user", "a"])
def test_unknown_user_is_reported_as_not_found(api, identifier):
    response = api.post("/auth/login", json={"identifier": identifier, "password": "whatever"})

    assert response.status_code == 401
    assert response.json()["code"] == "user_not_found"


def test_unknown_email_without_reliable_check_is_not_guessed(api, backend):
    """If auth.users cannot be checked, a failed login stays "invalid credentials"."""
    backend.auth_gateway.existence_check_available = False

    response = api.post("/auth/login", json={"identifier": "ghost@example.com", "password": "x"})

    assert response.json()["code"] == "invalid_credentials"


def test_account_without_profile_and_wrong_password_is_not_reported_missing(api, backend):
    """Registered with email confirmation, never logged in: no profile row yet, but the account exists."""
    backend.auth_gateway.add_account("late@example.com", "Secret1!")

    response = api.post("/auth/login", json={"identifier": "late@example.com", "password": "wrong"})

    assert response.json()["code"] == "invalid_credentials"


def test_unconfirmed_email(api, backend):
    backend.auth_gateway.confirm_email = True
    assert register(api).json()["session"] is None

    response = api.post("/auth/login", json={"identifier": "anna@example.com", "password": "Secret1!"})

    assert response.json()["code"] == "email_not_confirmed"


def test_username_saved_at_first_login_after_confirmation(api, backend):
    backend.auth_gateway.confirm_email = True
    register(api)
    backend.auth_gateway.accounts["anna@example.com"]["confirmed"] = True

    api.post("/auth/login", json={"identifier": "anna@example.com", "password": "Secret1!"})

    response = api.post("/auth/login", json={"identifier": "anna_k", "password": "Secret1!"})
    assert response.status_code == 200


def test_username_login_when_column_is_missing(api, backend, monkeypatch):
    def broken(_):
        raise RuntimeError("column users.username does not exist")

    monkeypatch.setattr(backend.users, "get_by_username", broken)

    response = api.post("/auth/login", json={"identifier": "anna_k", "password": "Secret1!"})

    assert response.status_code == 503
    assert response.json()["code"] == "username_login_unavailable"
    assert "does not exist" not in response.text


def test_refresh_and_session_expired_code(api):
    tokens = register(api).json()["session"]

    assert api.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]}).status_code == 200
    expired = api.post("/auth/refresh", json={"refresh_token": "bogus"})
    assert expired.status_code == 401 and expired.json()["code"] == "session_expired"


def test_unexpected_errors_do_not_leak(api, backend, monkeypatch):
    def crash(*_):
        raise RuntimeError("relation \"secret_internal_table\" does not exist")

    monkeypatch.setattr(backend.auth, "login", crash)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/auth/login", json={"identifier": "a@b.cd", "password": "x"})

    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error", "code": "internal_error"}


# --- validation codes (the same rules the clients get from GET /auth/config) ---------------------


def test_auth_config_publishes_the_rules(api):
    config = api.get("/auth/config").json()

    assert config["password_min_length"] == 6          # Supabase default, PASSWORD_MIN_LENGTH
    assert config["username_pattern"] == "^[a-z0-9_.-]{3,30}$"
    assert config["username_required"] is True


@pytest.mark.parametrize("body, code", [
    ({"email": "", "username": "anna_k", "password": "Secret1!"}, "email_required"),
    ({"email": "not-an-email", "username": "anna_k", "password": "Secret1!"}, "invalid_email"),
    ({"email": "a@b.cd", "username": "", "password": "Secret1!"}, "username_required"),
    ({"email": "a@b.cd", "username": "Ab", "password": "Secret1!"}, "invalid_username"),
    ({"email": "a@b.cd", "username": "anna k", "password": "Secret1!"}, "invalid_username"),
    ({"email": "a@b.cd", "username": "anna_k", "password": ""}, "password_required"),
    ({"email": "a@b.cd", "username": "anna_k", "password": "12345"}, "password_too_short"),
    ({"email": "a@b.cd", "username": "anna_k", "password": "Secret1!", "password_confirm": "Secret2!"},
     "password_mismatch"),
])
def test_registration_problems_have_codes(api, body, code):
    response = api.post("/auth/register", json=body)

    assert response.status_code == 422
    assert response.json()["code"] == code
    assert response.json()["password_min_length"] == 6


def test_all_registration_problems_are_listed(api):
    response = api.post("/auth/register", json={"email": "x", "username": "", "password": "1"})

    assert response.json()["problems"] == ["invalid_email", "username_required", "password_too_short"]


@pytest.mark.parametrize("body, code", [
    ({"identifier": "", "password": "x"}, "identifier_required"),
    ({"identifier": "anna", "password": ""}, "password_required"),
])
def test_login_problems_have_codes(api, body, code):
    response = api.post("/auth/login", json=body)

    assert (response.status_code, response.json()["code"]) == (422, code)


def test_malformed_body_has_a_code(api):
    response = api.post("/auth/login", content=b"{not json", headers={"Content-Type": "application/json"})

    assert response.status_code == 422 and response.json()["code"] == "validation_error"


def _desktop_auth_rules():
    """desktop/app/auth_rules.py (only depends on `re`; loaded by path: both packages are called `app`)."""
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "desktop" / "app" / "auth_rules.py"
    spec = importlib.util.spec_from_file_location("desktop_auth_rules", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("email, username, password, confirm", [
    ("anna@example.com", "anna_k", "Secret1!", "Secret1!"),
    ("", "", "", ""),
    ("bad-email", "A", "123", "124"),
    ("a@b", "anna", "Secret1!", "Secret1!"),
    ("  Anna@Example.com ", "Anna.K", "Secret1!", "Secret2!"),
    ("anna@example.com", "has space", "x" * 73, "x" * 73),
    ("anna@example.com", "ab", "12345", "12345"),
    ("anna@example.com", "a" * 31, "пароль", "пароль"),
])
def test_desktop_rules_match_the_backend(email, username, password, confirm):
    """The desktop client must flag exactly what the server rejects (same codes, same order)."""
    from app.core import auth_policy

    desktop = _desktop_auth_rules()
    policy = auth_policy.policy()
    assert desktop.registration_problems(email, username, password, confirm, policy) == \
        auth_policy.registration_problems(email, username, password, confirm)
    # the fallback used before /auth/config has answered is the same policy
    assert {k: policy[k] for k in desktop.DEFAULT_POLICY} == desktop.DEFAULT_POLICY


@pytest.mark.parametrize("identifier, password", [("", ""), ("anna", ""), ("  ", "x"), ("anna", "x")])
def test_desktop_login_rules_match_the_backend(identifier, password):
    from app.core import auth_policy

    assert _desktop_auth_rules().login_problems(identifier, password) == auth_policy.login_problems(identifier, password)
