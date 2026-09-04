from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

import devbox._transport as transport_module
from devbox import ProtocolError, ServiceUnavailableError
from devbox._transport import AsyncTransport, SyncTransport


def test_retries_connection_establishment_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(transport_module, "_CONNECT_RETRY_DELAYS", (0.0, 0.0))
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise httpx.ConnectError("connection refused", request=request)
        return httpx.Response(200, json={"status": "ready"})

    with _transport(handler) as transport:
        assert transport.request("POST", "/sandboxes", json_body={}) == {"status": "ready"}

    assert attempts == 3


def test_does_not_retry_server_errors() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(503, json={"message": "unavailable"})

    with _transport(handler) as transport, pytest.raises(ServiceUnavailableError):
        transport.request("GET", "/sandboxes")

    assert attempts == 1


def test_does_not_hide_programming_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise RuntimeError("broken callback")

    with _transport(handler) as transport, pytest.raises(RuntimeError, match="broken callback"):
        transport.request("GET", "/sandboxes")


def test_rejects_redirects() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "https://login.test"})

    with (
        _transport(handler) as transport,
        pytest.raises(ProtocolError, match="unexpected redirect"),
    ):
        transport.request("GET", "/sandboxes")


def test_connect_stream_rejects_redirects() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "https://login.test"})

    with (
        _transport(handler) as transport,
        pytest.raises(ProtocolError, match="unexpected redirect"),
    ):
        next(transport.connect_stream("/process.Process/Start", {}))


@pytest.mark.asyncio
async def test_async_retries_connection_establishment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(transport_module, "_CONNECT_RETRY_DELAYS", (0.0,))
    attempts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ConnectError("connection refused", request=request)
        return httpx.Response(200, json={"status": "ready"})

    transport = AsyncTransport(
        "https://api.test",
        headers={},
        timeout=30,
        transport=httpx.MockTransport(handler),
    )
    try:
        assert await transport.request("POST", "/sandboxes", json_body={}) == {"status": "ready"}
    finally:
        await transport.close()

    assert attempts == 2


def _transport(
    handler: Callable[[httpx.Request], httpx.Response],
) -> SyncTransport:
    return SyncTransport(
        "https://api.test",
        headers={},
        timeout=30,
        transport=httpx.MockTransport(handler),
    )
