from __future__ import annotations

import base64
import json
from collections.abc import Mapping
from typing import Any

import httpx

from devbox import CommandHandle
from devbox._transport import SyncTransport
from devbox.commands import Commands
from devbox.pty import Pty


def test_pty_reconnect_returns_interactive_handle() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/Connect"):
            return _stream_response(
                {"event": {"start": {"pid": 42}}},
                {"event": {"data": {"pty": _encoded("ready\n")}}},
                {"event": {"end": {"exitCode": 0}}},
            )
        return httpx.Response(200, json={})

    with _transport(handler) as transport:
        commands = Commands(lambda: transport)
        session = Pty(commands, lambda: transport).connect(42)
        assert isinstance(session, CommandHandle)
        session.send_stdin("exit\n")
        result = session.wait()

    assert result.stdout == "ready\n"
    assert requests[1].url.path == "/process.Process/SendInput"
    assert json.loads(requests[1].content) == {
        "process": {"pid": 42},
        "input": {"pty": _encoded("exit\n")},
    }


def _transport(handler: Any) -> SyncTransport:
    return SyncTransport(
        "https://envd.test",
        headers={},
        timeout=30,
        transport=httpx.MockTransport(handler),
    )


def _stream_response(*events: Mapping[str, Any]) -> httpx.Response:
    body = b"".join(_frame(event) for event in events) + _frame({}, flags=2)
    return httpx.Response(200, content=body, headers={"Content-Type": "application/connect+json"})


def _frame(value: Mapping[str, Any], *, flags: int = 0) -> bytes:
    data = json.dumps(value, separators=(",", ":")).encode()
    return bytes([flags]) + len(data).to_bytes(4, "big") + data


def _encoded(value: str) -> str:
    return base64.b64encode(value.encode()).decode()
