"""Supabase Auth behind one boundary: sign up / sign in / refresh / sign out / existence check.

Supabase errors are converted to AuthGatewayError with a normalized code, so the
service layer never parses raw library messages and never forwards them to clients.
"""

import logging

from app.core.supabase import create_auth_client, get_supabase

logger = logging.getLogger("minidrive")


class AuthGatewayError(Exception):
    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code


def _normalize(exc: Exception) -> AuthGatewayError:
    raw_code = (getattr(exc, "code", None) or "").lower()
    message = (getattr(exc, "message", None) or str(exc) or "").lower()

    if raw_code == "invalid_credentials" or "invalid login credentials" in message:
        code = "invalid_credentials"
    elif raw_code == "email_not_confirmed" or "email not confirmed" in message:
        code = "email_not_confirmed"
    elif raw_code in {"user_already_exists", "email_exists"} or "already registered" in message:
        code = "user_exists"
    elif raw_code == "weak_password" or "password should" in message:
        code = "weak_password"
    elif raw_code == "email_address_invalid" or "invalid format" in message:
        code = "invalid_email"
    elif "rate limit" in raw_code or "rate limit" in message:
        code = "rate_limited"
    elif raw_code in {"refresh_token_not_found", "refresh_token_already_used", "session_not_found"}:
        code = "session_expired"
    else:
        code = "auth_failed"
    if code == "auth_failed":
        logger.warning("Supabase Auth error (%s): %s", raw_code or type(exc).__name__, exc)
    return AuthGatewayError(code, str(exc))


class SupabaseAuthGateway:

    def sign_up(self, email: str, password: str, metadata: dict):
        try:
            return create_auth_client().auth.sign_up({
                "email": email,
                "password": password,
                "options": {"data": metadata},
            })
        except Exception as exc:
            raise _normalize(exc) from exc

    def sign_in(self, email: str, password: str):
        try:
            return create_auth_client().auth.sign_in_with_password({"email": email, "password": password})
        except Exception as exc:
            raise _normalize(exc) from exc

    def refresh(self, refresh_token: str):
        try:
            return create_auth_client().auth.refresh_session(refresh_token)
        except Exception as exc:
            raise _normalize(exc) from exc

    def sign_out(self, access_token: str) -> None:
        """Revoke the user's refresh tokens. The access token itself expires on its own."""
        try:
            get_supabase().auth.admin.sign_out(access_token)
        except Exception:
            # already expired / revoked sessions are fine to "log out"
            pass

    def user_exists(self, email: str) -> bool | None:
        """Whether an Auth account exists for this email.

        Uses public.auth_user_exists (supabase/schema.sql), which only the
        service role may execute. Returns None when the check is unavailable,
        so callers never guess.
        """
        try:
            result = get_supabase().rpc("auth_user_exists", {"p_email": email}).execute().data
        except Exception as exc:
            logger.warning("auth_user_exists check unavailable: %s", exc)
            return None
        return result if isinstance(result, bool) else None
