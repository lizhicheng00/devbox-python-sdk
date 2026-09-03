from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest

from devbox import (
    AsyncDevBox,
    ConfigurationError,
    DevBox,
    NetworkConfig,
    ProtocolError,
    RateLimitError,
    SandboxState,
)
from devbox.config import ConnectionConfig
from devbox.models import SandboxConnection
from devbox.sandbox import _gateway_url


def test_create_uses_manager_contract() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(201, json=connection_response())

    with client(handler) as api:
        sandbox = api.sandboxes.create(
            "python",
            timeout=300,
            envs={"A": "1"},
            metadata={"job": "test"},
            network=NetworkConfig(allow_public_traffic=True),
        )

    body = json.loads(captured[0].content)
    assert captured[0].url.path == "/sandboxes"
    assert captured[0].headers["X-API-Key"] == "secret"
    assert body["templateID"] == "python"
    assert body["envVars"] == {"A": "1"}
    assert body["autoResume"] == {"enabled": False}
    assert "autoPauseMemory" not in body
    assert body["network"]["allowPublicTraffic"] is True
    assert sandbox.sandbox_id == "sbx_123"


def test_v2_list_reads_pagination_headers() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v2/sandboxes"
        assert request.url.params["state"] == "running,paused"
        return httpx.Response(
            200,
            json=[detail_response()],
            headers={"X-Next-Token": "next", "X-Total-Running": "7"},
        )

    with client(handler) as api:
        page = api.sandboxes.list(states=[SandboxState.RUNNING, SandboxState.PAUSED], limit=10)

    assert page.next_token == "next"
    assert page.total == 7
    assert page.items[0].sandbox_id == "sbx_123"


def test_lifecycle_uses_documented_paths_and_bodies() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        if request.url.path == "/sandboxes":
            return httpx.Response(201, json=connection_response())
        if request.url.path.endswith("/snapshots"):
            return httpx.Response(201, json={"snapshotID": "snap_1", "names": ["checkpoint"]})
        return httpx.Response(204)

    with client(handler) as api:
        sandbox = api.sandboxes.create()
        sandbox.refresh(120)
        snapshot = sandbox.snapshot("checkpoint")
        sandbox.pause(memory=False)

    assert [item.url.path for item in captured] == [
        "/sandboxes",
        "/sandboxes/sbx_123/refreshes",
        "/sandboxes/sbx_123/snapshots",
        "/sandboxes/sbx_123/pause",
    ]
    assert json.loads(captured[1].content) == {"duration": 120}
    assert snapshot.names == ("checkpoint",)


def test_logs_metrics_and_aggregate_metrics() -> None:
    metric = {
        "timestampUnix": 1,
        "cpuCount": 2,
        "cpuUsedPct": 25.5,
        "memUsed": 10,
        "memTotal": 20,
        "memCache": 1,
        "diskUsed": 30,
        "diskTotal": 40,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/sandboxes":
            return httpx.Response(201, json=connection_response())
        if request.url.path.endswith("/logs"):
            return httpx.Response(
                200,
                json={
                    "logs": [
                        {
                            "timestamp": "2026-09-02T00:00:00Z",
                            "level": "INFO",
                            "message": "ready",
                            "fields": {"source": "vm"},
                        }
                    ]
                },
            )
        if request.url.path == "/sandboxes/metrics":
            return httpx.Response(200, json={"sandboxes": {"sbx_123": metric}})
        return httpx.Response(200, json=[metric])

    with client(handler) as api:
        sandbox = api.sandboxes.create()
        logs = sandbox.get_logs(search="ready")
        metrics = sandbox.get_metrics(start=1, end=2)
        aggregate = api.sandboxes.metrics(["sbx_123"])

    assert logs[0].message == "ready"
    assert metrics[0].cpu_used_percent == 25.5
    assert aggregate["sbx_123"].disk_total_bytes == 40


def test_error_shape_preserves_message_and_code() -> None:
    with (
        client(
            lambda request: httpx.Response(
                429, json={"error": "rate_limited", "message": "too many requests"}
            )
        ) as api,
        pytest.raises(RateLimitError) as raised,
    ):
        api.sandboxes.get("sbx_123")
    assert raised.value.code == "rate_limited"
    assert raised.value.message == "too many requests"


@pytest.mark.asyncio
async def test_async_client_uses_same_contract() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-API-Key"] == "secret"
        return httpx.Response(201, json=connection_response("sbx_async"))

    async with AsyncDevBox(
        api_key="secret", api_url="https://api.test", http_transport=httpx.MockTransport(handler)
    ) as api:
        sandbox = await api.sandboxes.create()
    assert sandbox.sandbox_id == "sbx_async"


@pytest.mark.asyncio
async def test_async_sandbox_context_deletes_remote_sandbox() -> None:
    methods: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        if request.method == "POST":
            return httpx.Response(201, json=connection_response("sbx_async"))
        return httpx.Response(204)

    async with AsyncDevBox(
        api_key="secret",
        api_url="https://api.test",
        http_transport=httpx.MockTransport(handler),
    ) as api:
        async with await api.sandboxes.create() as sandbox:
            assert sandbox.sandbox_id == "sbx_async"
        assert sandbox.info.state is SandboxState.STOPPED

    assert methods == ["POST", "DELETE"]


def test_invalid_pagination_header_is_a_protocol_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[], headers={"X-Total-Running": "invalid"})

    with client(handler) as api, pytest.raises(ProtocolError, match="X-Total-Running"):
        api.sandboxes.list()


def test_https_gateway_url_can_override_manager_placeholder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEVBOX_GATEWAY_URL", "https://gateway.example.test/")
    config = ConnectionConfig.resolve(api_key="secret")
    connection = SandboxConnection(
        sandbox_id="sbx_123",
        gateway_url="https://sbx_123.sandbox.devbox.local",
        access_token="token",
    )

    assert _gateway_url(connection, config.gateway_url) == "https://gateway.example.test"


def test_gateway_url_override_requires_https(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEVBOX_GATEWAY_URL", "http://gateway.example.test")

    with pytest.raises(ConfigurationError, match="must use https"):
        ConnectionConfig.resolve(api_key="secret")


def test_sandbox_context_deletes_remote_sandbox() -> None:
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        if request.method == "POST":
            return httpx.Response(201, json=connection_response())
        return httpx.Response(204)

    with client(handler) as api:
        with api.sandboxes.create() as sandbox:
            assert sandbox.sandbox_id == "sbx_123"
        assert sandbox.info.state is SandboxState.STOPPED

    assert methods == ["POST", "DELETE"]


def test_kill_is_idempotent() -> None:
    delete_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal delete_count
        if request.method == "POST":
            return httpx.Response(201, json=connection_response())
        delete_count += 1
        if delete_count == 1:
            return httpx.Response(204)
        return httpx.Response(404, json={"code": "not_found", "message": "not found"})

    with client(handler) as api:
        sandbox = api.sandboxes.create()
        assert sandbox.kill() is True
        assert sandbox.kill() is False


def test_is_running_returns_false_when_sandbox_is_missing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(201, json=connection_response())
        return httpx.Response(404, json={"code": "not_found", "message": "not found"})

    with client(handler) as api:
        sandbox = api.sandboxes.create()
        assert sandbox.is_running() is False


def client(handler: Callable[[httpx.Request], httpx.Response]) -> DevBox:
    return DevBox(
        api_key="secret", api_url="https://api.test", http_transport=httpx.MockTransport(handler)
    )


def connection_response(sandbox_id: str = "sbx_123") -> dict[str, object]:
    return {
        "templateID": "base",
        "sandboxID": sandbox_id,
        "clientID": "client_1",
        "envdVersion": "1.0.0",
        "envdAccessToken": "",
        "domain": "",
    }


def detail_response() -> dict[str, object]:
    return {
        **connection_response(),
        "startedAt": "2026-09-02T00:00:00Z",
        "endAt": "2026-09-02T00:05:00Z",
        "cpuCount": 2,
        "memoryMB": 512,
        "diskSizeMB": 10240,
        "state": "running",
    }
