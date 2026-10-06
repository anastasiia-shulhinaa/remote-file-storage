"""Environment-driven backend configuration.

Values are read from environment variables and, for local development,
from ``backend/.env``. See ``backend/.env.example`` for the full contract.
All secrets here are server-only and must never be sent to a client.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"

    # Comma-separated list of browser origins allowed to call the API.
    cors_origins: str = "http://localhost:5173"

    # Server-only secrets. Optional until the features that use them exist
    # (database: TASK-005, Supabase Auth: TASK-010, Storage: TASK-020).
    database_url: SecretStr | None = None
    supabase_url: str | None = None
    supabase_anon_key: SecretStr | None = None
    supabase_service_role_key: SecretStr | None = None
    supabase_jwt_secret: SecretStr | None = None
    supabase_storage_bucket: str = "minidrive-files"

    max_upload_size_mb: int = 50

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
