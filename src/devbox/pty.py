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
        body: dict[str, object] = {
            "command": command,
            "envs": dict(envs or {}),
            "stdin": True,
            "timeout": None,
        }
        if cwd:
            body["cwd"] = cwd
        if user:
            body["user"] = user
        return self._commands._start_background(body, pty=size)

    def connect(
        self,
        pid: int,
        *,
        on_data: OutputHandler | None = None,
        timeout: float | None = None,
    ) -> CommandResult:
        return self._commands.connect(pid).wait(
            timeout=timeout, on_stdout=on_data, on_stderr=on_data, check=False
        )

    def resize(self, pid: int, size: PtySize) -> None:
        self._transport().request(
            "POST",
            "/envd/process/update",
            json_body={"pid": pid, "pty": {"rows": size.rows, "cols": size.cols}},
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
        body: dict[str, object] = {
            "command": command,
            "envs": dict(envs or {}),
            "stdin": True,
            "timeout": None,
        }
        if cwd:
            body["cwd"] = cwd
        if user:
            body["user"] = user
        return await self._commands._start_background(body, pty=size)

    async def connect(
        self,
        pid: int,
        *,
        on_data: AsyncOutputHandler | None = None,
        timeout: float | None = None,
    ) -> CommandResult:
        return await self._commands.connect(pid).wait(
            timeout=timeout, on_stdout=on_data, on_stderr=on_data, check=False
        )

    async def resize(self, pid: int, size: PtySize) -> None:
        transport = await self._transport()
        await transport.request(
            "POST",
            "/envd/process/update",
            json_body={"pid": pid, "pty": {"rows": size.rows, "cols": size.cols}},
        )
