from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.supabase import get_supabase

security = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class CurrentUser:
    """Identity taken from a verified Supabase JWT — never from the request body."""

    id: UUID
    email: str
    access_token: str


def verify_supabase_token(token: str | None) -> CurrentUser | None:
    """Verify a Supabase access token and return the user, or None if it is invalid/expired.

    auth.get_claims verifies the signature locally with the project's JWKS
    (asymmetric keys) or falls back to asking Supabase Auth (legacy HS256 keys).
    """
    if not token:
        return None
    try:
        result = get_supabase().auth.get_claims(jwt=token)
    except Exception:
        return None
    claims = (result or {}).get("claims") or {}
    subject = claims.get("sub")
    if not subject or claims.get("role") == "anon":
        return None
    try:
        user_id = UUID(subject)
    except ValueError:
        return None
    return CurrentUser(id=user_id, email=claims.get("email") or "", access_token=token)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> CurrentUser:
    user = verify_supabase_token(credentials.credentials if credentials else None)
    if user is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user
