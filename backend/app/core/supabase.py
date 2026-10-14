import threading

from supabase import Client, ClientOptions, create_client

from app.core.config import settings

_local = threading.local()


def _options() -> ClientOptions:
    # The backend is stateless: never keep or auto-refresh a session in-process.
    return ClientOptions(auto_refresh_token=False, persist_session=False)


def get_supabase() -> Client:
    """Trusted server-side client (secret / service-role key), one per thread.

    Used for database, storage and token verification. Never call
    sign_in / sign_up on it: that would replace its service-role
    Authorization header with a user's token.

    supabase-py talks HTTP/2 over a single shared connection, and that connection
    is not safe to use from several threads at once: concurrent requests from
    FastAPI's threadpool failed at random (httpx.ReadError, WinError 10035), which
    surfaced as internal_error / history_unavailable during synchronization.
    Each worker thread therefore gets its own client.
    """
    client = getattr(_local, "client", None)
    if client is None:
        if not settings.supabase_url or not settings.supabase_key:
            raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be set in backend/.env")
        client = create_client(settings.supabase_url, settings.supabase_key, options=_options())
        _local.client = client
    return client


def create_auth_client() -> Client:
    """Fresh client with the publishable/anon key for one sign up / sign in call."""
    key = settings.supabase_anon_key or settings.supabase_key
    if not settings.supabase_url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_ANON_KEY must be set in backend/.env")
    return create_client(settings.supabase_url, key, options=_options())
