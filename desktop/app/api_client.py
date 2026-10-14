"""HTTP client for the MiniDrive FastAPI backend. The desktop never talks to Supabase directly."""

from pathlib import Path

import httpx


class ApiError(Exception):
    """A failed request. `code` is the stable machine-readable error code from the API
    (translated for the user by app.i18n); `detail` is technical text, never shown as is."""

    def __init__(self, status_code: int, detail: str, code: str | None = None, extra: dict | None = None):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.code = code or ("network_error" if status_code == 0 else f"http_{status_code}")
        self.extra = extra or {}

    def __str__(self) -> str:
        return f"{self.detail} (HTTP {self.status_code})" if self.status_code else self.detail


def _error(response: httpx.Response) -> ApiError:
    try:
        body = response.json()
    except Exception:
        return ApiError(response.status_code, response.text or response.reason_phrase)
    detail = body.get("detail") if isinstance(body, dict) else None
    code = body.get("code") if isinstance(body, dict) else None
    if isinstance(detail, list):  # FastAPI 422 validation errors
        code = code or "validation_error"
        detail = "; ".join(str(d.get("msg", d)) for d in detail)
    extra = {k: v for k, v in body.items() if k not in ("detail", "code")} if isinstance(body, dict) else {}
    return ApiError(response.status_code, str(detail), code, extra)


class ApiClient:

    def __init__(self, base_url: str, client: httpx.Client | None = None):
        self.base_url = base_url.rstrip("/")
        self.access_token: str | None = None
        self.refresh_token: str | None = None
        self.user: dict | None = None
        # injectable for tests (e.g. FastAPI's TestClient talking to the real backend app)
        self.client = client or httpx.Client(base_url=self.base_url, timeout=60)

    def headers(self) -> dict:
        if not self.access_token:
            return {}
        return {"Authorization": f"Bearer {self.access_token}"}

    # --- plumbing -------------------------------------------------------------

    def _request(self, method: str, url: str, retry: bool = True, **kwargs) -> httpx.Response:
        try:
            response = self.client.request(method, url, headers=self.headers(), **kwargs)
        except httpx.HTTPError as exc:
            raise ApiError(0, f"Server is not reachable: {exc}", "network_error") from exc

        # access tokens live ~1 hour: refresh once and retry
        if response.status_code == 401 and retry and self.refresh_token:
            if self._try_refresh():
                for value in kwargs.get("files", {}).values():
                    handle = value[1] if isinstance(value, tuple) else None
                    if hasattr(handle, "seek"):
                        handle.seek(0)
                return self._request(method, url, retry=False, **kwargs)

        if response.status_code >= 400:
            raise _error(response)
        return response

    def _store_session(self, data: dict) -> dict:
        self.access_token = data["access_token"]
        self.refresh_token = data["refresh_token"]
        self.user = data["user"]
        return data

    def _try_refresh(self) -> bool:
        try:
            response = self.client.post("/auth/refresh", json={"refresh_token": self.refresh_token})
        except httpx.HTTPError:
            return False
        if response.status_code != 200:
            return False
        self._store_session(response.json())
        return True

    # --- auth -----------------------------------------------------------------

    def availability(self, email: str | None = None, username: str | None = None) -> dict:
        """Registration form: {"email": "available" | "taken" | "invalid" | "unknown", ...}."""
        params = {k: v for k, v in (("email", email), ("username", username)) if v}
        return self._request("GET", "/auth/availability", retry=False, params=params).json()

    def auth_config(self) -> dict:
        """Registration/login rules published by the backend (password length, username format)."""
        return self._request("GET", "/auth/config", retry=False).json()

    def register(self, email: str, password: str, display_name: str | None = None,
                 username: str | None = None, password_confirm: str | None = None) -> dict:
        data = self._request("POST", "/auth/register", retry=False, json={
            "email": email, "password": password, "password_confirm": password_confirm,
            "display_name": display_name or None, "username": username or "",
        }).json()
        if data.get("session"):
            self._store_session(data["session"])
        return data

    def login(self, identifier: str, password: str) -> dict:
        """identifier: an email or a username (resolved by the backend)."""
        data = self._request("POST", "/auth/login", retry=False, json={
            "identifier": identifier, "password": password,
        }).json()
        return self._store_session(data)

    def logout(self) -> None:
        try:
            if self.access_token:
                self._request("POST", "/auth/logout", retry=False)
        except ApiError:
            pass
        finally:
            self.access_token = self.refresh_token = self.user = None

    def me(self) -> dict:
        return self._request("GET", "/auth/me").json()

    # --- folders --------------------------------------------------------------

    def get_folders(self) -> list[dict]:
        return self._request("GET", "/folders").json()

    def create_folder(self, name: str, parent_folder_id: str | None = None) -> dict:
        return self._request("POST", "/folders", json={
            "name": name, "parent_folder_id": parent_folder_id,
        }).json()

    def ensure_folder_path(self, path: str, parent_folder_id: str | None = None) -> dict:
        """Create a nested folder path such as "Project/src" (existing folders are reused)."""
        return self._request("POST", "/folders/path", json={
            "path": path, "parent_folder_id": parent_folder_id,
        }).json()

    def delete_folder(self, folder_id: str) -> None:
        self._request("DELETE", f"/folders/{folder_id}")

    def clear_folder(self, folder_id: str) -> dict:
        """Delete all files and subfolders of a folder; the folder itself stays."""
        return self._request("DELETE", f"/folders/{folder_id}/contents").json()

    # --- files ----------------------------------------------------------------

    def get_files(
        self,
        folder_id: str | None = None,
        extension: str | None = None,
        sort: str = "created_at",
        order: str = "desc",
        recursive: bool = False,
    ) -> list[dict]:
        """recursive: also the files of all subfolders, each with folder_path (its location)."""
        params = {"sort": sort, "order": order}
        if folder_id:
            params["folder_id"] = folder_id
        if extension:
            params["extension"] = extension
        if recursive:
            params["recursive"] = "true"
        return self._request("GET", "/files", params=params).json()

    def get_file(self, file_id: str) -> dict:
        return self._request("GET", f"/files/{file_id}").json()

    def upload_file(
        self,
        path: Path,
        folder_id: str | None = None,
        relative_dir: str | None = None,
        modified_at: str | None = None,
        synchronization_id: str | None = None,
    ) -> dict:
        """synchronization_id: the change is part of a sync and is journaled for rollback."""
        path = Path(path)
        data = {}
        if folder_id:
            data["folder_id"] = folder_id
        if relative_dir:
            data["relative_dir"] = relative_dir
        if modified_at:
            data["modified_at"] = modified_at
        if synchronization_id:
            data["synchronization_id"] = synchronization_id
        with path.open("rb") as handle:
            return self._request(
                "POST", "/files",
                data=data,
                files={"file": (path.name, handle, "application/octet-stream")},
                timeout=300,
            ).json()

    def download_file(self, file_id: str) -> bytes:
        return self._request("GET", f"/files/{file_id}/content", timeout=300).content

    def delete_file(self, file_id: str, synchronization_id: str | None = None) -> None:
        params = {"synchronization_id": synchronization_id} if synchronization_id else None
        self._request("DELETE", f"/files/{file_id}", params=params)

    def get_preview(self, file_id: str) -> dict:
        return self._request("GET", f"/files/{file_id}/preview").json()

    # --- synchronization ------------------------------------------------------

    def post_sync(self, remote_folder_id: str, manifest: list[dict], mode: str = "two_way",
                  device: str | None = None) -> dict:
        return self._request("POST", "/sync", json={
            "remote_folder_id": remote_folder_id,
            "manifest": manifest,
            "mode": mode,
            "client": "desktop",
            "device": device,
        }).json()

    def report_synchronization(self, synchronization_id: str, status: str, counts: dict | None = None,
                               error: str | None = None) -> dict:
        """Progress (RUNNING) or the result (COMPLETED / FAILED) of an executed plan."""
        return self._request("PATCH", f"/synchronizations/{synchronization_id}", json={
            **(counts or {}), "status": status, "error": error,
        }).json()

    def get_synchronizations(self, limit: int = 20) -> list[dict]:
        return self._request("GET", "/synchronizations", params={"limit": limit}).json()

    def get_synchronization(self, synchronization_id: str) -> dict:
        return self._request("GET", f"/synchronizations/{synchronization_id}").json()

    def cancel_sync(self, synchronization_id: str) -> dict:
        return self._request("POST", f"/sync/{synchronization_id}/cancel").json()

    def rollback_sync(self, synchronization_id: str) -> dict:
        return self._request("POST", f"/sync/{synchronization_id}/rollback").json()

    def finish_rollback(self, synchronization_id: str, local_restored: int, local_failures: list[dict],
                        counts: dict | None = None) -> dict:
        """counts: what had been done before the cancel (kept in the history)."""
        return self._request("POST", f"/sync/{synchronization_id}/rollback/finish", json={
            "local_restored": local_restored, "local_failures": local_failures, "counts": counts,
        }).json()

    # --- settings -------------------------------------------------------------

    def get_column_settings(self) -> dict:
        return self._request("GET", "/settings/columns").json()

    def update_column_settings(self, changes: dict) -> dict:
        return self._request("PATCH", "/settings/columns", json=changes).json()
