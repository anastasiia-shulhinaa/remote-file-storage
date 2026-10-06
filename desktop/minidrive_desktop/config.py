"""Desktop client configuration.

Reads ``MINIDRIVE_API_URL`` from the environment or from ``desktop/.env``.
The desktop client only needs the backend URL; it never holds Supabase
service-role or database credentials.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

DESKTOP_DIR = Path(__file__).resolve().parent.parent
DEFAULT_API_URL = "http://127.0.0.1:8000"


@dataclass(frozen=True)
class DesktopConfig:
    api_url: str
    request_timeout_seconds: float = 10.0


def load_config() -> DesktopConfig:
    load_dotenv(DESKTOP_DIR / ".env")
    api_url = os.environ.get("MINIDRIVE_API_URL", DEFAULT_API_URL).rstrip("/")
    return DesktopConfig(api_url=api_url)
