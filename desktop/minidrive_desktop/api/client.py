"""REST client for the MiniDrive FastAPI backend.

All backend communication from the desktop client goes through ApiClient,
so GUI code never builds HTTP requests itself.
"""

from dataclasses import dataclass
from typing import Any

import httpx


class ApiError(Exception):
    """Raised when the backend is unreachable or returns an error response."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class HealthStatus:
    status: str
    service: str
    version: str
    environment: str


class ApiClient:
    def __init__(
        self,
        base_url: str,
        timeout: float = 10.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._http = httpx.Client(base_url=base_url, timeout=timeout, transport=transport)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "ApiClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def health(self) -> HealthStatus:
        data = self._request("GET", "/health")
        return HealthStatus(
            status=data["status"],
            service=data["service"],
            version=data["version"],
            environment=data["environment"],
        )

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = self._http.request(method, path, **kwargs)
        except httpx.RequestError as exc:
            raise ApiError(f"Cannot reach backend at {self._http.base_url}: {exc}") from exc

        if response.is_error:
            raise ApiError(
                f"Backend returned {response.status_code} for {method} {path}",
                status_code=response.status_code,
            )
        return response.json()
