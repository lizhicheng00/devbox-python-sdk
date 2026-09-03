from __future__ import annotations

import base64
import json
from collections.abc import Mapping
from typing import Any

import httpx
import pytest

from devbox import CommandExitError, CommandResult
from devbox._transport import AsyncTransport, SyncTransport
from devbox.commands import AsyncCommands, CommandHandle, Commands


def test_command_uses_envd_connect_protocol() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.path == "/process.Process/Start"
        body = _request_frame(request)
        assert body == {
            "process": {
                "cmd": "/bin/bash",
                "args": ["-l", "-c", "echo hello"],
                "envs": {"LANG": "C"},
                "cwd": "/tmp",
            },
            "stdin": False,
        }
        return _stream_response(
            {"event": {"start": {"pid": 42}}},
            {"event": {"data": {"stdout": _encoded("hello ")}}},
            {"event": {"data": {"stderr": _encoded("warning\n")}}},
            {"event": {"data": {"stdout": _encoded("world\n")}}},
            {"event": {"end": {"exitCode": 0, "exited": True}}},
        )

    output: list[str] = []
    with _transport(handler) as transport:
        result = Commands(lambda: transport).run(
            "echo hello", envs={"LANG": "C"}, cwd="/tmp", on_stdout=output.append
        )

    assert isinstance(result, CommandResult)
    assert result == CommandResult(exit_code=0, stdout="hello world\n", stderr="warning\n", pid=42)
    assert output == ["hello ", "world\n"]
    assert requests[0].headers["Content-Type"] == "application/connect+json"
    assert requests[0].headers["Connect-Protocol-Version"] == "1"


def test_nonzero_command_raises_with_result() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _stream_response(
            {"event": {"start": {"pid": 7}}},
            {"event": {"end": {"exitCode": 7, "exited": True}}},
        )

    with _transport(handler) as transport, pytest.raises(CommandExitError) as raised:
        Commands(lambda: transport).run("exit 7")

    assert raised.value.result.exit_code == 7


def test_background_command_keeps_stream_and_sends_base64_input() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/Start"):
            return _stream_response(
                {"event": {"start": {"pid": 42}}},
                {"event": {"end": {"exited": True}}},
            )
        return httpx.Response(200, json={}, headers={"Content-Type": "application/json"})

    with _transport(handler) as transport:
        handle = Commands(lambda: transport).run("cat", background=True, stdin=True)
        assert isinstance(handle, CommandHandle)
        handle.send_stdin("ready\n")
        result = handle.wait()

    assert result.exit_code == 0
    assert requests[1].url.path == "/process.Process/SendInput"
    assert json.loads(requests[1].content) == {
        "process": {"pid": 42},
        "input": {"stdin": _encoded("ready\n")},
    }


def test_background_callbacks_are_attached_when_waiting() -> None:
    with _transport(lambda request: httpx.Response(500)) as transport:
        commands = Commands(lambda: transport)
        with pytest.raises(ValueError, match=r"handle\.wait"):
            commands.run(  # type: ignore[call-overload]
                "echo ready", background=True, on_stdout=lambda chunk: None
            )


@pytest.mark.asyncio
async def test_async_command_uses_the_same_protocol() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return _stream_response(
            {"event": {"start": {"pid": 8}}},
            {"event": {"data": {"stdout": _encoded("async")}}},
            {"event": {"end": {"exited": True}}},
        )

    transport = AsyncTransport(
        "https://envd.test",
        headers={},
        timeout=30,
        transport=httpx.MockTransport(handler),
    )

    async def provide() -> AsyncTransport:
        return transport

    try:
        result = await AsyncCommands(provide).run("echo async")
    finally:
        await transport.close()

    assert isinstance(result, CommandResult)
    assert result.stdout == "async"


def _transport(handler: Any) -> SyncTransport:
    return SyncTransport(
        "https://envd.test",
        headers={},
        timeout=30,
        transport=httpx.MockTransport(handler),
    )


def _request_frame(request: httpx.Request) -> Mapping[str, Any]:
    content = request.content
    assert content[0] == 0
    size = int.from_bytes(content[1:5], "big")
    assert size == len(content) - 5
    value = json.loads(content[5:])
    assert isinstance(value, Mapping)
    return value


def _stream_response(*events: Mapping[str, Any]) -> httpx.Response:
    body = b"".join(_frame(event) for event in events) + _frame({}, flags=2)
    return httpx.Response(200, content=body, headers={"Content-Type": "application/connect+json"})


def _frame(value: Mapping[str, Any], *, flags: int = 0) -> bytes:
    data = json.dumps(value, separators=(",", ":")).encode()
    return bytes([flags]) + len(data).to_bytes(4, "big") + data


def _encoded(value: str) -> str:
    return base64.b64encode(value.encode()).decode()
