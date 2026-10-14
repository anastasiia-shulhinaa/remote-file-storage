from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.core.auth_policy import login_problems, raise_problems, registration_problems
from app.core.validation import normalize_username


class RegisterRequest(BaseModel):
    """Checked by app.core.auth_policy (the same rules the clients get from GET /auth/config);
    a problem is answered with 422 and a code such as invalid_email or password_too_short."""

    email: str = Field(default="", max_length=1000)
    password: str = Field(default="", max_length=1000)
    password_confirm: str | None = Field(default=None, max_length=1000)
    display_name: str | None = Field(default=None, max_length=100)
    username: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def _check(self):
        raise_problems(registration_problems(self.email, self.username, self.password, self.password_confirm))
        self.email = self.email.strip().lower()
        self.username = normalize_username(self.username)
        return self


class LoginRequest(BaseModel):
    """Log in with an email or a username.

    `identifier` is the new field; `email` is kept so older clients keep working.
    """

    identifier: str | None = Field(default=None, max_length=254)
    email: str | None = Field(default=None, max_length=254)
    password: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def _check(self):
        value = (self.identifier or self.email or "").strip()
        raise_problems(login_problems(value, self.password))
        self.identifier = value
        return self


class RefreshRequest(BaseModel):
    refresh_token: str


class UserDto(BaseModel):
    id: UUID
    email: str
    display_name: str
    username: str | None = None
    root_folder_id: UUID | None = None


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int | None = None
    user: UserDto


class RegisterResponse(BaseModel):
    user_id: UUID
    email: str
    # None when Supabase requires email confirmation before the first login
    session: TokenResponse | None = None
    message: str
