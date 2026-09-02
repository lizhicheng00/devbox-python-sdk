from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any

import pytest

from devbox import CommandExitError, CommandResult
from devbox.commands import CommandHandle, Commands


class CommandTransport:
    def __init__(self, events: list[Mapping[str, Any]] | None = None) -> None:
        self.events = events or []
        self.requests: list[tuple[str, str, object]] = []

    def request(self, method: str, path: str, *, json_body: object | None = None) -> object:
        self.requests.append((method, path, json_body))
        return {"pid": 42}

    def iter_events(
        self, method: str, path: str, *, json_body: object | None = None
    ) -> Iterator[Mapping[str, Any]]:
        self.requests.append((method, path, json_body))
        yield from self.events


def test_command_stream_combines_output_and_calls_handlers() -> None:
    transport = CommandTransport(
        [
            {"type": "stdout", "data": "hello ", "pid": 42},
            {"type": "stderr", "data": "warning\n"},
            {"type": "stdout", "data": "world\n"},
            {"type": "exit", "exitCode": 0},
        ]
    )
    output: list[str] = []
    commands = Commands(lambda: transport)  # type: ignore[arg-type]

    result = commands.run("echo hello", on_stdout=output.append)

    assert isinstance(result, CommandResult)
    assert result.stdout == "hello world\n"
    assert result.stderr == "warning\n"
    assert result.pid == 42
    assert output == ["hello ", "world\n"]


def test_nonzero_command_raises_with_result() -> None:
    transport = CommandTransport([{"type": "exit", "exitCode": 7}])
    commands = Commands(lambda: transport)  # type: ignore[arg-type]

    with pytest.raises(CommandExitError) as raised:
        commands.run("exit 7")

    assert raised.value.result.exit_code == 7


def test_background_command_returns_reconnectable_handle() -> None:
    transport = CommandTransport()
    commands = Commands(lambda: transport)  # type: ignore[arg-type]

    handle = commands.run("python server.py", background=True)

    assert isinstance(handle, CommandHandle)
    assert handle.pid == 42
    handle.send_stdin("ready\n")
    assert transport.requests[-1][1] == "/envd/process/send-input"
