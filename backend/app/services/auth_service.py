import logging
from uuid import UUID

from app.core.errors import (
    BadRequestError,
    ConflictError,
    ServiceUnavailableError,
    UnauthorizedError,
    ValidationError,
)
from app.core.auth_policy import is_valid_email
from app.core.validation import is_valid_username, normalize_username
from app.repositories.auth_gateway import AuthGatewayError, SupabaseAuthGateway
from app.repositories.user_repository import UserRepository
from app.schemas.auth import (
    LoginRequest,
    RegisterRequest,
    RegisterResponse,
    TokenResponse,
    UserDto,
)
from app.services.folder_service import FolderService

logger = logging.getLogger("minidrive")


class AuthService:
    """Registration and login through Supabase Auth. Passwords never touch our tables.

    Login accepts an email or a username. A username is resolved to the email on
    the server (public.users), then Supabase Auth checks the password as usual.
    """

    def __init__(
        self,
        user_repository: UserRepository | None = None,
        folder_service: FolderService | None = None,
        gateway: SupabaseAuthGateway | None = None,
    ):
        self.users = user_repository or UserRepository()
        self.folders = folder_service or FolderService()
        self.gateway = gateway or SupabaseAuthGateway()

    # --- registration ----------------------------------------------------------

    def register(self, request: RegisterRequest) -> RegisterResponse:
        email = request.email
        username = request.username
        display_name = (request.display_name or "").strip() or username or email.split("@")[0]

        if username and self._find_by_username(username, required=True) is not None:
            raise ConflictError("Username is already taken", code="username_taken")

        metadata = {"display_name": display_name}
        if username:
            metadata["username"] = username
        try:
            response = self.gateway.sign_up(email, request.password, metadata)
        except AuthGatewayError as exc:
            raise self._registration_error(exc) from exc

        user = response.user
        if user is None:
            raise BadRequestError("Registration failed", code="registration_failed")
        # with email confirmation on, Supabase hides existing accounts behind a user without identities
        if getattr(user, "identities", None) == []:
            raise ConflictError("User already registered", code="user_exists")

        user_id = UUID(str(user.id))
        if response.session is None:
            # email confirmation is on: the profile and root folder are created at first login
            return RegisterResponse(
                user_id=user_id,
                email=email,
                message="Registered. Confirm your email, then log in.",
            )

        profile = self.ensure_profile(user_id, email, display_name, username)
        return RegisterResponse(
            user_id=user_id,
            email=email,
            session=self._token_response(response.session, profile),
            message="Registered and logged in.",
        )

    @staticmethod
    def _registration_error(exc: AuthGatewayError) -> Exception:
        if exc.code == "user_exists":
            return ConflictError("User already registered", code="user_exists")
        if exc.code in {"weak_password", "invalid_email"}:
            # e.g. a stricter Supabase password policy than password_min_length
            return ValidationError("Registration data rejected", code=exc.code)
        if exc.code == "rate_limited":
            return BadRequestError("Too many attempts", code="rate_limited")
        return BadRequestError("Registration failed", code="registration_failed")

    # --- login -----------------------------------------------------------------

    def login(self, request: LoginRequest) -> TokenResponse:
        identifier = (request.identifier or "").strip()
        profile: dict | None

        if "@" in identifier:
            email = identifier.lower()
            profile = self._find_by_email(email)
        else:
            username = normalize_username(identifier)
            if not is_valid_username(username):
                # such a username can never have been registered
                raise UnauthorizedError("User not found", code="user_not_found")
            profile = self._find_by_username(username, required=True)
            if profile is None:
                raise UnauthorizedError("User not found", code="user_not_found")
            email = profile["email"]

        try:
            response = self.gateway.sign_in(email, request.password)
        except AuthGatewayError as exc:
            raise self._login_error(exc, email, profile) from exc

        if response.session is None or response.user is None:
            raise UnauthorizedError("Invalid login credentials", code="invalid_credentials")

        user = response.user
        metadata = user.user_metadata or {}
        resolved_email = user.email or email
        profile_dto = self.ensure_profile(
            UUID(str(user.id)),
            resolved_email,
            metadata.get("display_name") or resolved_email.split("@")[0],
            metadata.get("username"),
        )
        return self._token_response(response.session, profile_dto)

    def _login_error(self, exc: AuthGatewayError, email: str, profile: dict | None) -> Exception:
        if exc.code == "email_not_confirmed":
            return UnauthorizedError("Email not confirmed", code="email_not_confirmed")
        if exc.code == "rate_limited":
            return UnauthorizedError("Too many attempts", code="rate_limited")
        if exc.code != "invalid_credentials":
            return ServiceUnavailableError("Authentication service error", code="auth_unavailable")

        # Supabase answers "invalid_credentials" both for a wrong password and for an
        # unknown email. Say "not found" only when that is known for certain:
        # a profile proves the account exists; otherwise ask auth.users directly.
        exists = True if profile is not None else self.gateway.user_exists(email)
        if exists is False:
            return UnauthorizedError("User not found", code="user_not_found")
        return UnauthorizedError("Invalid login credentials", code="invalid_credentials")

    # --- session -----------------------------------------------------------------

    def refresh(self, refresh_token: str) -> TokenResponse:
        try:
            response = self.gateway.refresh(refresh_token)
        except AuthGatewayError as exc:
            raise UnauthorizedError("Session expired, log in again", code="session_expired") from exc
        if response.session is None or response.user is None:
            raise UnauthorizedError("Session expired, log in again", code="session_expired")
        profile = self.get_profile(UUID(str(response.user.id)), response.user.email or "")
        return self._token_response(response.session, profile)

    def logout(self, access_token: str) -> None:
        self.gateway.sign_out(access_token)

    # --- profile -----------------------------------------------------------------

    def ensure_profile(
        self,
        user_id: UUID,
        email: str,
        display_name: str,
        username: str | None = None,
    ) -> UserDto:
        profile = self.users.get(user_id)
        if profile is None:
            profile = self._create_profile(user_id, email, display_name, username)
        root = self.folders.ensure_root(user_id)
        return UserDto(
            id=profile["id"],
            email=profile["email"],
            display_name=profile["display_name"],
            username=profile.get("username"),
            root_folder_id=root["id"],
        )

    def _create_profile(self, user_id: UUID, email: str, display_name: str, username: str | None) -> dict:
        username = normalize_username(username) if username else None
        if username and not is_valid_username(username):
            username = None
        try:
            return self.users.upsert(user_id, email, display_name, username)
        except Exception as exc:
            if not username:
                raise
            # username taken meanwhile, or the username column is missing (migration not run):
            # the account still works with email login
            logger.warning("Profile saved without username %r: %s", username, exc)
            return self.users.upsert(user_id, email, display_name)

    def get_profile(self, user_id: UUID, email: str) -> UserDto:
        return self.ensure_profile(user_id, email, email.split("@")[0] or "user")

    # --- availability (registration form, while typing) ------------------------------

    def availability(self, email: str | None, username: str | None) -> dict:
        """"available" / "taken" / "invalid" / "unknown" for each given field.

        Lets the registration form warn at once that an email or username is taken.
        (It reveals whether an account exists — the price of that convenience.)
        """
        result: dict[str, str] = {}
        if email is not None:
            email = email.strip().lower()
            if not is_valid_email(email):
                result["email"] = "invalid"
            else:
                exists = self.gateway.user_exists(email)  # auth.users: also unconfirmed accounts
                if exists is None:  # auth_user_exists() is not installed: fall back to the profiles
                    try:
                        exists = self.users.get_by_email(email) is not None
                    except Exception as exc:
                        logger.warning("Email availability check failed: %s", exc)
                result["email"] = "unknown" if exists is None else ("taken" if exists else "available")
        if username is not None:
            username = normalize_username(username)
            if not is_valid_username(username):
                result["username"] = "invalid"
            else:
                try:
                    taken = self.users.get_by_username(username) is not None
                except Exception as exc:
                    logger.warning("Username availability check failed: %s", exc)
                    result["username"] = "unknown"
                else:
                    result["username"] = "taken" if taken else "available"
        return result

    # --- lookups -------------------------------------------------------------------

    def _find_by_email(self, email: str) -> dict | None:
        try:
            return self.users.get_by_email(email)
        except Exception as exc:
            logger.warning("Profile lookup by email failed: %s", exc)
            return None

    def _find_by_username(self, username: str, required: bool = False) -> dict | None:
        try:
            return self.users.get_by_username(username)
        except Exception as exc:
            # typically: users.username does not exist yet (supabase/schema.sql not re-run)
            logger.error("Profile lookup by username failed: %s", exc)
            if required:
                raise ServiceUnavailableError(
                    "Username login is unavailable", code="username_login_unavailable"
                ) from exc
            return None

    @staticmethod
    def _token_response(session, profile: UserDto) -> TokenResponse:
        return TokenResponse(
            access_token=session.access_token,
            refresh_token=session.refresh_token,
            expires_in=session.expires_in,
            user=profile,
        )
