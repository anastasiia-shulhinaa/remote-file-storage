"""Detects a database that is older than the code (a Supabase migration was not applied).

Without this, a missing column only shows up as a vague failure deep inside a request.
/health reports the result, the log says which migration to run, and synchronization
answers with the clear code "schema_outdated" instead of misbehaving.
"""

import logging
import time

logger = logging.getLogger("nastusha")

# (description, table, columns) — what the current code needs
REQUIRED = [
    ("002_minidrive.sql", "users", "username"),
    ("002_minidrive.sql", "column_visibility_settings", "user_id"),
    ("002_minidrive.sql", "synchronizations", "id,status,client"),
    ("003_sync_rollback.sql", "synchronizations", "updated_at,rollback_report,device"),
    ("003_sync_rollback.sql", "sync_operations", "id,seq,status"),
]
_CACHE_SECONDS = 60
_cache: tuple[float, list[str]] | None = None


def is_missing_schema(exc: BaseException) -> bool:
    """PostgreSQL / PostgREST errors meaning "this table or column does not exist"."""
    text = str(exc)
    return any(marker in text for marker in ("42703", "42P01", "PGRST204", "PGRST205", "does not exist",
                                             "Could not find the table", "schema cache"))


def missing_migrations(force: bool = False) -> list[str]:
    """Migration files whose objects are missing (cached for a minute)."""
    global _cache
    if not force and _cache and time.monotonic() - _cache[0] < _CACHE_SECONDS:
        return _cache[1]
    from app.core.supabase import get_supabase

    missing: list[str] = []
    try:
        client = get_supabase()
    except Exception:
        return []  # not configured (e.g. tests): nothing to report
    for migration, table, columns in REQUIRED:
        try:
            client.table(table).select(columns).limit(1).execute()
        except Exception as exc:
            if is_missing_schema(exc) and migration not in missing:
                missing.append(migration)
    if missing:
        logger.error("Database schema is outdated: run supabase/migrations/%s in the Supabase SQL Editor",
                     ", ".join(missing))
    _cache = (time.monotonic(), missing)
    return missing
