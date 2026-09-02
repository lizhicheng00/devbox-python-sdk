from __future__ import annotations

import json

import httpx
import pytest

from devbox import AsyncDevBox, DevBox, NetworkConfig, RateLimitError, SandboxState


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


def client(handler: object) -> DevBox:
    return DevBox(
        api_key="secret", api_url="https://api.test", http_transport=httpx.MockTransport(handler)
    )  # type: ignore[arg-type]


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
