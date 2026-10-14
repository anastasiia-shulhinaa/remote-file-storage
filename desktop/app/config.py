"""Where the desktop client finds the MiniDrive API.

The address is configuration, not something users type or see:
  1. the MINIDRIVE_API_URL environment variable (NASTUSHA_API_URL is still accepted),
  2. desktop/minidrive.ini:   [api]
                              url = https://minidrive.example.com
  3. the local development server http://127.0.0.1:8000.
It is deliberately not stored in the user's settings: a stale saved address would
silently break every start.
"""

import configparser
import os
from pathlib import Path

DEFAULT_API_URL = "http://127.0.0.1:8000"
CONFIG_FILE = Path(__file__).resolve().parents[1] / "minidrive.ini"


def api_url() -> str:
    for name in ("MINIDRIVE_API_URL", "NASTUSHA_API_URL"):
        value = (os.environ.get(name) or "").strip()
        if value:
            return value.rstrip("/")
    if CONFIG_FILE.is_file():
        parser = configparser.ConfigParser()
        parser.read(CONFIG_FILE, encoding="utf-8")
        value = parser.get("api", "url", fallback="").strip()
        if value:
            return value.rstrip("/")
    return DEFAULT_API_URL
