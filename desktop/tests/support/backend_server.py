"""The real FastAPI backend with in-memory fakes instead of Supabase, for desktop integration tests.

usage: python backend_server.py <port>     (run in its own process: backend and desktop are both "app")
Account: anna@example.com / anna / secret1
"""

import sys
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "tests")]

import uvicorn  # noqa: E402
from fastapi import Depends, HTTPException  # noqa: E402
from fastapi.security import HTTPAuthorizationCredentials  # noqa: E402

from app.api import deps  # noqa: E402
from app.core.security import CurrentUser, get_current_user, security  # noqa: E402
from app.main import app  # noqa: E402
from fakes import FakeBackend  # noqa: E402

backend = FakeBackend()
account = backend.auth_gateway.add_account(
    "anna@example.com", "secret1", metadata={"display_name": "Anna", "username": "anna"}
)
backend.users.upsert(UUID(account["id"]), "anna@example.com", "Anna", "anna")
backend.folders.ensure_root(UUID(account["id"]))


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(security)):
    token = credentials.credentials if credentials else ""
    for acc in backend.auth_gateway.accounts.values():
        if token == f"access-{acc['id']}":
            return CurrentUser(id=UUID(acc["id"]), email=acc["email"], access_token=token)
    raise HTTPException(401, "Invalid or expired token")


@app.post("/__test__/remote-state")
def remote_state():
    """Everything a sync can change remotely (rows + bytes, backups excluded) — for assertions."""
    return {
        "files": backend.file_repo.rows,
        "folders": backend.folder_repo.rows,
        "objects": {k: v.decode("latin-1") for k, v in backend.storage.objects.items() if "/.sync-backups/" not in k},
        "backups": sorted(k for k in backend.storage.objects if "/.sync-backups/" in k),
    }


# routes added after import come after the static web mount at "/": move this one first
app.router.routes.insert(0, app.router.routes.pop())


app.dependency_overrides[get_current_user] = current_user
app.dependency_overrides[deps.get_folder_service] = lambda: backend.folders
app.dependency_overrides[deps.get_file_service] = lambda: backend.files
app.dependency_overrides[deps.get_auth_service] = lambda: backend.auth
app.dependency_overrides[deps.get_sync_service] = lambda: backend.sync
app.dependency_overrides[deps.get_settings_service] = lambda: backend.settings

uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[1]), log_level="warning")
