"""Validation of user-supplied names and paths (path traversal protection)."""

import re
import unicodedata

from app.core.errors import ValidationError

MAX_NAME_LENGTH = 255
_FORBIDDEN_CHARS = set('/\\:*?"<>|')
_STORAGE_SAFE = re.compile(r"[^A-Za-z0-9._-]+")
# usernames are case-insensitive and stored in lower case; "@" is never allowed,
# so a login identifier with "@" is always an email
USERNAME_PATTERN = r"^[a-z0-9_.-]{3,30}$"
_USERNAME = re.compile(USERNAME_PATTERN)


def validate_name(name: str | None, kind: str = "File") -> str:
    """Validate a single file or folder name and return it stripped."""
    name = (name or "").strip()
    if not name:
        raise ValidationError(f"{kind} name is required", code="name_required")
    if len(name) > MAX_NAME_LENGTH:
        raise ValidationError(f"{kind} name is too long", code="name_too_long")
    if name in {".", ".."}:
        raise ValidationError(f"Invalid {kind.lower()} name", code="invalid_name")
    if any(ch in _FORBIDDEN_CHARS or ord(ch) < 32 for ch in name):
        raise ValidationError(f"Invalid {kind.lower()} name: {name!r}", code="invalid_name")
    return name


def split_relative_path(path: str | None) -> list[str]:
    """Split "labs/lab1/main.cpp" into validated segments. Rejects "..", absolute paths."""
    path = (path or "").replace("\\", "/").strip()
    if not path:
        return []
    if path.startswith("/") or re.match(r"^[A-Za-z]:", path):
        raise ValidationError(f"Path must be relative: {path!r}", code="invalid_path")
    segments = [s for s in path.split("/") if s not in {"", "."}]
    return [validate_name(s, "Path segment") for s in segments]


def get_extension(name: str) -> str:
    """'Main.CPP' → '.cpp', 'Makefile' → '', '.gitignore' → ''."""
    stem, dot, ext = name.rpartition(".")
    if not dot or not stem or not ext:
        return ""
    return "." + ext.lower()


def normalize_extension(extension: str | None) -> str | None:
    """User filter input 'jpg' / '.JPG' → '.jpg'; empty → None (no filter)."""
    extension = (extension or "").strip().lower()
    if not extension:
        return None
    return extension if extension.startswith(".") else "." + extension


def safe_storage_name(name: str) -> str:
    """ASCII-only object name for Supabase Storage keys; the real name stays in the DB."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    safe = _STORAGE_SAFE.sub("_", ascii_name).strip("._")
    return safe[:100] or "file"


def normalize_username(value: str | None) -> str:
    return (value or "").strip().lower()


def is_valid_username(value: str) -> bool:
    return bool(_USERNAME.fullmatch(value))
