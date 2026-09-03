from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping

from ._transport import AsyncTransport, SyncTransport
from .commands import (
    AsyncCommandHandle,
    AsyncCommands,
    AsyncOutputHandler,
    CommandHandle,
    Commands,
    OutputHandler,
)
from .models import CommandResult, PtySize


class Pty:
    def __init__(self, commands: Commands, transport: Callable[[], SyncTransport]) -> None:
        self._commands = commands
        self._transport = transport

    def start(
        self,
        command: str = "/bin/bash",
        *,
        size: PtySize | None = None,
        envs: Mapping[str, str] | None = None,
        cwd: str | None = None,
        user: str | None = None,
    ) -> CommandHandle:
        size = size or PtySize()
        environment = {"TERM": "xterm-256color", "LANG": "C.UTF-8", **dict(envs or {})}
        body: dict[str, object] = {
            "process": {
                "cmd": command,
                "args": ["-i", "-l"] if command == "/bin/bash" else [],
                "envs": environment,
            }
        }
        if cwd:
            process = body["process"]
            assert isinstance(process, dict)
            process["cwd"] = cwd
        return self._commands._start(body, timeout=None, user=user, pty=size, input_stream="pty")

    def connect(
        self,
        pid: int,
        *,
        on_data: OutputHandler | None = None,
        timeout: float | None = None,
    ) -> CommandResult:
        return CommandHandle(pid, self._commands, input_stream="pty").wait(
            timeout=timeout, on_stdout=on_data, on_stderr=on_data, check=False
        )

    def resize(self, pid: int, size: PtySize) -> None:
        self._transport().connect_unary(
            "/process.Process/Update",
            json_body={
                "process": {"pid": pid},
                "pty": {"size": {"rows": size.rows, "cols": size.cols}},
            },
        )


class AsyncPty:
    def __init__(
        self,
        commands: AsyncCommands,
        transport: Callable[[], Awaitable[AsyncTransport]],
    ) -> None:
        self._commands = commands
        self._transport = transport

    async def start(
        self,
        command: str = "/bin/bash",
        *,
        size: PtySize | None = None,
        envs: Mapping[str, str] | None = None,
        cwd: str | None = None,
        user: str | None = None,
    ) -> AsyncCommandHandle:
        size = size or PtySize()
        environment = {"TERM": "xterm-256color", "LANG": "C.UTF-8", **dict(envs or {})}
        body: dict[str, object] = {
            "process": {
                "cmd": command,
                "args": ["-i", "-l"] if command == "/bin/bash" else [],
                "envs": environment,
            }
        }
        if cwd:
            process = body["process"]
            assert isinstance(process, dict)
            process["cwd"] = cwd
        return await self._commands._start(
            body, timeout=None, user=user, pty=size, input_stream="pty"
        )

    async def connect(
        self,
        pid: int,
        *,
        on_data: AsyncOutputHandler | None = None,
        timeout: float | None = None,
    ) -> CommandResult:
        return await AsyncCommandHandle(pid, self._commands, input_stream="pty").wait(
            timeout=timeout, on_stdout=on_data, on_stderr=on_data, check=False
        )

    async def resize(self, pid: int, size: PtySize) -> None:
        transport = await self._transport()
        await transport.connect_unary(
            "/process.Process/Update",
            json_body={
                "process": {"pid": pid},
                "pty": {"size": {"rows": size.rows, "cols": size.cols}},
            },
        )
