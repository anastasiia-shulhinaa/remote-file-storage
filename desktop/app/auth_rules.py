"""Client-side check of the login / registration form (same rules and codes as the web client).

The rules come from the backend (GET /auth/config, backend/app/core/auth_policy.py),
which checks them again; DEFAULT_POLICY is only used until the server has answered.
"""

import re

DEFAULT_POLICY = {
    "password_min_length": 6,
    "password_max_length": 72,
    "email_pattern": r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    "username_pattern": r"^[a-z0-9_.-]{3,30}$",
    "username_required": True,
    "password_require_uppercase": True,
    "password_require_special": True,
}


def has_uppercase(password: str) -> bool:
    return any(ch.isupper() for ch in password)


def has_special(password: str) -> bool:
    """A sign that is neither a letter, a digit nor a space: ! @ # $ % _ - . , etc."""
    return any(not ch.isalnum() and not ch.isspace() for ch in password)


def load_policy(api) -> dict:
    try:
        return {**DEFAULT_POLICY, **api.auth_config()}
    except Exception:
        return dict(DEFAULT_POLICY)


def registration_problems(email: str, username: str, password: str, password_confirm: str, policy: dict) -> list[str]:
    problems = []
    email = (email or "").strip()
    if not email:
        problems.append("email_required")
    elif len(email) > 254 or not re.match(policy["email_pattern"], email):
        problems.append("invalid_email")

    username = (username or "").strip().lower()
    if not username:
        if policy.get("username_required", True):
            problems.append("username_required")
    elif not re.fullmatch(policy["username_pattern"], username):
        problems.append("invalid_username")

    if not password:
        problems.append("password_required")
    elif len(password) < policy["password_min_length"]:
        problems.append("password_too_short")
    elif len(password.encode()) > policy["password_max_length"]:
        problems.append("password_too_long")
    else:
        if policy.get("password_require_uppercase") and not has_uppercase(password):
            problems.append("password_needs_uppercase")
        if policy.get("password_require_special") and not has_special(password):
            problems.append("password_needs_special")

    if password and password != password_confirm:
        problems.append("password_mismatch")
    return problems


def login_problems(identifier: str, password: str) -> list[str]:
    problems = []
    if not (identifier or "").strip():
        problems.append("identifier_required")
    if not password:
        problems.append("password_required")
    return problems
