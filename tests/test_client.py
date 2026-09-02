from __future__ import annotations

import json

import httpx
import pytest

from devbox import (
    AsyncDevBox,
    DevBox,
    NetworkConfig,
    RateLimitError,
    SandboxState,
)


def test_create_sandbox_sends_auth_and_returns_connected_sandbox() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(201, json=sandbox_response())

    with DevBox(
        api_key="devbox_secret",
        api_url="https://api.example.test",
        http_transport=httpx.MockTransport(handler),
    ) as client:
        sandbox = client.sandboxes.create(
            "python",
            timeout=300,
            envs={"A": "1"},
            metadata={"job": "test"},
            network=NetworkConfig(allow_public_traffic=True),
        )

    request = captured[0]
    body = json.loads(request.content)
    assert request.method == "POST"
    assert request.url.path == "/sandboxes"
    assert request.headers["X-API-Key"] == "devbox_secret"
    assert request.headers["Idempotency-Key"]
    assert body["template"] == "python"
    assert body["network"]["allowPublicTraffic"] is True
    assert sandbox.sandbox_id == "sbx_123"
    assert sandbox.info.state is SandboxState.RUNNING


def test_list_sandboxes_supports_pagination() -> None:
    response = sandbox_response()["sandbox"]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["state"] == "running,paused"
        assert request.url.params["limit"] == "10"
        return httpx.Response(200, json={"sandboxes": [response], "nextToken": "next-page"})

    with DevBox(
        api_key="devbox_secret",
        api_url="https://api.example.test",
        http_transport=httpx.MockTransport(handler),
    ) as client:
        page = client.sandboxes.list(states=[SandboxState.RUNNING, SandboxState.PAUSED], limit=10)

    assert page.next_token == "next-page"
    assert page.items[0].sandbox_id == "sbx_123"


def test_refresh_and_snapshot_listing_use_lifecycle_endpoints() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/sandboxes":
            return httpx.Response(201, json=sandbox_response())
        if request.url.path.endswith("/refresh"):
            return httpx.Response(204)
        return httpx.Response(
            200,
            json={
                "snapshots": [
                    {
                        "snapshotId": "snap_123",
                        "sandboxId": "sbx_123",
                        "createdAt": "2026-09-02T00:00:00Z",
                    }
                ]
            },
        )

    with DevBox(
        api_key="devbox_secret",
        api_url="https://api.example.test",
        http_transport=httpx.MockTransport(handler),
    ) as client:
        sandbox = client.sandboxes.create()
        sandbox.refresh()
        snapshots = client.snapshots.list()

    assert paths == ["/sandboxes", "/sandboxes/sbx_123/refresh", "/snapshots"]
    assert snapshots.items[0].snapshot_id == "snap_123"


def test_rate_limit_error_preserves_service_details() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            headers={"Retry-After": "2", "X-Request-Id": "req-1"},
            json={
                "error": {
                    "code": "RATE_LIMITED",
                    "message": "too many requests",
                    "target": "sandbox",
                }
            },
        )

    with (
        DevBox(
            api_key="devbox_secret",
            api_url="https://api.example.test",
            http_transport=httpx.MockTransport(handler),
        ) as client,
        pytest.raises(RateLimitError) as raised,
    ):
        client.sandboxes.get("sbx_123")

    assert raised.value.code == "RATE_LIMITED"
    assert raised.value.status_code == 429
    assert raised.value.retry_after == 2
    assert raised.value.request_id == "req-1"


@pytest.mark.asyncio
async def test_async_client_matches_sync_lifecycle() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-API-Key"] == "devbox_secret"
        return httpx.Response(201, json=sandbox_response("sbx_async"))

    async with AsyncDevBox(
        api_key="devbox_secret",
        api_url="https://api.example.test",
        http_transport=httpx.MockTransport(handler),
    ) as client:
        sandbox = await client.sandboxes.create()

    assert sandbox.sandbox_id == "sbx_async"


@pytest.mark.parametrize("timeout", [0, 3601])
def test_sandbox_timeout_is_bounded(timeout: int) -> None:
    with (
        DevBox(
            api_key="devbox_secret",
            api_url="https://api.example.test",
            http_transport=httpx.MockTransport(
                lambda request: httpx.Response(500, request=request)
            ),
        ) as client,
        pytest.raises(ValueError, match="between 1 and 3600"),
    ):
        client.sandboxes.create(timeout=timeout)


def sandbox_response(sandbox_id: str = "sbx_123") -> dict[str, object]:
    return {
        "sandbox": {
            "sandboxId": sandbox_id,
            "templateId": "python",
            "state": "running",
            "createdAt": "2026-09-02T00:00:00Z",
            "updatedAt": "2026-09-02T00:00:00Z",
            "timeout": 300,
            "expiresAt": "2026-09-02T00:05:00Z",
            "metadata": {"job": "test"},
            "network": {
                "allowInternetAccess": True,
                "allowPublicTraffic": False,
            },
        },
        "connection": {
            "gatewayUrl": "https://gateway.example.test",
            "accessToken": "connection-token",
            "expiresAt": "2099-09-02T00:05:00Z",
        },
    }
