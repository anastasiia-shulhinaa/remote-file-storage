"""Registration / login input rules: one source of truth for the backend and both clients.

The clients read these rules from GET /auth/config and check the form before sending it;
the backend checks again and answers with machine-readable codes the clients translate.

password_min_length must match the Supabase project (Authentication → Providers → Email →
"Minimum password length"; Supabase's default is 6). Configure it with PASSWORD_MIN_LENGTH.
Stricter Supabase rules (e.g. required digits) are reported back as "weak_password".
"""

import re

from app.core.config import settings
from app.core.errors import ValidationError
from app.core.validation import USERNAME_PATTERN, normalize_username

EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
USERNAME_MIN, USERNAME_MAX = 3, 30
PASSWORD_MAX_LENGTH = 72  # bcrypt limit used by Supabase Auth

_EMAIL = re.compile(EMAIL_PATTERN)
_USERNAME = re.compile(USERNAME_PATTERN)


def policy() -> dict:
    return {
        "password_min_length": settings.password_min_length,
        "password_max_length": PASSWORD_MAX_LENGTH,
        "email_pattern": EMAIL_PATTERN,
        "username_pattern": USERNAME_PATTERN,
        "username_min_length": USERNAME_MIN,
        "username_max_length": USERNAME_MAX,
        "username_required": True,
        "password_require_uppercase": True,
        "password_require_special": True,
    }


def is_valid_email(email: str) -> bool:
    return bool(email) and len(email) <= 254 and bool(_EMAIL.match(email))


def has_uppercase(password: str) -> bool:
    return any(ch.isupper() for ch in password)  # Latin and Cyrillic


def has_special(password: str) -> bool:
    """A sign that is neither a letter, a digit nor a space: ! @ # $ % _ - . , etc."""
    return any(not ch.isalnum() and not ch.isspace() for ch in password)


def registration_problems(email: str, username: str, password: str, password_confirm: str | None) -> list[str]:
    problems = []
    email = (email or "").strip()
    if not email:
        problems.append("email_required")
    elif len(email) > 254 or not _EMAIL.match(email):
        problems.append("invalid_email")

    username = normalize_username(username)
    if not username:
        problems.append("username_required")
    elif not _USERNAME.fullmatch(username):
        problems.append("invalid_username")

    if not password:
        problems.append("password_required")
    elif len(password) < settings.password_min_length:
        problems.append("password_too_short")
    elif len(password.encode()) > PASSWORD_MAX_LENGTH:
        problems.append("password_too_long")
    else:
        # only for new passwords: existing accounts keep logging in with theirs
        if not has_uppercase(password):
            problems.append("password_needs_uppercase")
        if not has_special(password):
            problems.append("password_needs_special")

    if password_confirm is not None and password and password != password_confirm:
        problems.append("password_mismatch")
    return problems


def login_problems(identifier: str, password: str) -> list[str]:
    problems = []
    if not (identifier or "").strip():
        problems.append("identifier_required")
    if not password:
        problems.append("password_required")
    return problems


def raise_problems(problems: list[str]) -> None:
    """422 with the first problem as `code` and all of them in `problems`."""
    if problems:
        raise ValidationError(
            "Invalid input",
            code=problems[0],
            extra={"problems": problems, "password_min_length": settings.password_min_length},
        )
