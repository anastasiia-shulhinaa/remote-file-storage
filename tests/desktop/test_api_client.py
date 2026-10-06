import httpx
import pytest

from minidrive_desktop.api import ApiClient, ApiError

HEALTH_BODY = {
    "status": "ok",
    "service": "minidrive-backend",
    "version": "0.1.0",
    "environment": "test",
}


def client_with(handler) -> ApiClient:
    return ApiClient("http://backend.test", transport=httpx.MockTransport(handler))


def test_health_parses_backend_response():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/health"
        return httpx.Response(200, json=HEALTH_BODY)

    with client_with(handler) as client:
        health = client.health()

    assert health.status == "ok"
    assert health.version == "0.1.0"


def test_error_status_raises_api_error():
    with client_with(lambda request: httpx.Response(503)) as client:
        with pytest.raises(ApiError) as exc_info:
            client.health()

    assert exc_info.value.status_code == 503


def test_unreachable_backend_raises_api_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with client_with(handler) as client:
        with pytest.raises(ApiError) as exc_info:
            client.health()

    assert exc_info.value.status_code is None
