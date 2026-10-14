import re
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    supabase_url: str = ""
    # server-side secret / service-role key: backend only, never in clients
    supabase_key: str = ""
    # publishable / anon key: used for sign up / sign in
    supabase_anon_key: str = ""
    supabase_storage_bucket: str = "files"
    app_env: str = "development"
    # comma-separated list of allowed browser origins, e.g. "https://a.com,https://b.com"
    cors_origins: str = ""
    max_file_size: int = 50 * 1024 * 1024
    # must match Supabase Auth "Minimum password length" (Supabase default: 6)
    password_min_length: int = 6
    # built React client (npm run build); served by FastAPI when present
    web_dist_dir: Path = PROJECT_DIR / "web" / "dist"

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        extra="ignore",
    )

    @field_validator("supabase_url")
    @classmethod
    def _project_url(cls, value: str) -> str:
        """Accept the REST endpoint (https://x.supabase.co/rest/v1/) too: keep only the project URL."""
        value = value.strip().rstrip("/")
        return re.sub(r"/(rest|auth|storage)/v\d+$", "", value)

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
