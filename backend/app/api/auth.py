from fastapi import APIRouter, Depends, Query, Response

from app.api.deps import get_auth_service
from app.core.auth_policy import policy
from app.core.security import CurrentUser, get_current_user
from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    RegisterResponse,
    TokenResponse,
    UserDto,
)
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/config")
def auth_config():
    """Registration/login rules (password length, username and email format) for the clients."""
    return policy()


@router.get("/availability")
def availability(
    email: str | None = Query(None, max_length=254),
    username: str | None = Query(None, max_length=254),
    auth: AuthService = Depends(get_auth_service),
):
    """Registration form: is this email / username still free? Each given field gets
    "available", "taken", "invalid" or "unknown" (the check itself failed)."""
    return auth.availability(email, username)


@router.post("/register", response_model=RegisterResponse, status_code=201)
def register(
    request: RegisterRequest,
    auth: AuthService = Depends(get_auth_service),
):
    return auth.register(request)


@router.post("/login", response_model=TokenResponse)
def login(
    request: LoginRequest,
    auth: AuthService = Depends(get_auth_service),
):
    return auth.login(request)


@router.post("/refresh", response_model=TokenResponse)
def refresh(
    request: RefreshRequest,
    auth: AuthService = Depends(get_auth_service),
):
    return auth.refresh(request.refresh_token)


@router.post("/logout", status_code=204)
def logout(
    user: CurrentUser = Depends(get_current_user),
    auth: AuthService = Depends(get_auth_service),
):
    auth.logout(user.access_token)
    return Response(status_code=204)


@router.get("/me", response_model=UserDto)
def me(
    user: CurrentUser = Depends(get_current_user),
    auth: AuthService = Depends(get_auth_service),
):
    return auth.get_profile(user.id, user.email)
