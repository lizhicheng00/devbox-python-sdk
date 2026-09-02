from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from ._transport import AsyncTransport, SyncTransport
from .errors import CommandExitError, ProtocolError
from .models import CommandResult, OutputChunk, ProcessInfo, PtySize, parse_optional_datetime

OutputHandler = Callable[[str], None]
AsyncOutputHandler = Callable[[str], Awaitable[None] | None]
SyncTransportProvider = Callable[[], SyncTransport]
AsyncTransportProvider = Callable[[], Awaitable[AsyncTransport]]


class CommandHandle:
    def __init__(self, pid: int, commands: Commands) -> None:
        self.pid = pid
        self._commands = commands

    def wait(
        self,
        *,
        timeout: float | None = 60,
        on_stdout: OutputHandler | None = None,
        on_stderr: OutputHandler | None = None,
        check: bool = True,
    ) -> CommandResult:
        return self._commands._collect(
            "/envd/process/connect",
            {"pid": self.pid, "timeout": timeout},
            on_stdout,
            on_stderr,
            check,
        )

    def send_stdin(self, data: str | bytes) -> None:
        self._commands.send_stdin(self.pid, data)

    def close_stdin(self) -> None:
        self._commands.close_stdin(self.pid)

    def send_signal(self, signal: str) -> None:
        self._commands.send_signal(self.pid, signal)

    def kill(self) -> None:
        self.send_signal("SIGKILL")


class Commands:
    def __init__(self, transport: SyncTransportProvider) -> None:
        self._transport = transport

    def run(
        self,
        command: str,
        *,
        background: bool = False,
        envs: Mapping[str, str] | None = None,
        cwd: str | None = None,
        user: str | None = None,
        stdin: bool = False,
        timeout: float | None = 60,
        on_stdout: OutputHandler | None = None,
        on_stderr: OutputHandler | None = None,
        check: bool = True,
    ) -> CommandResult | CommandHandle:
        body = _command_body(command, envs, cwd, user, stdin, timeout)
        if background:
            return self._start_background(body)
        return self._collect("/envd/process/start", body, on_stdout, on_stderr, check)

    def connect(self, pid: int) -> CommandHandle:
        _validate_pid(pid)
        return CommandHandle(pid, self)

    def list(self) -> tuple[ProcessInfo, ...]:
        payload = self._transport().request("POST", "/envd/process/list", json_body={})
        values = _list_payload(payload, "processes")
        return tuple(ProcessInfo.from_wire(item) for item in values)

    def send_stdin(self, pid: int, data: str | bytes) -> None:
        _validate_pid(pid)
        self._transport().request(
            "POST",
            "/envd/process/send-input",
            json_body={"pid": pid, "data": _input(data)},
        )

    def close_stdin(self, pid: int) -> None:
        _validate_pid(pid)
        self._transport().request("POST", "/envd/process/close-stdin", json_body={"pid": pid})

    def send_signal(self, pid: int, signal: str) -> None:
        _validate_pid(pid)
        self._transport().request(
            "POST",
            "/envd/process/send-signal",
            json_body={"pid": pid, "signal": signal},
        )

    def _start_background(
        self, body: Mapping[str, object], pty: PtySize | None = None
    ) -> CommandHandle:
        request = dict(body)
        request["background"] = True
        if pty:
            request["pty"] = {"rows": pty.rows, "cols": pty.cols}
        payload = self._transport().request("POST", "/envd/process/start", json_body=request)
        pid = _pid(payload)
        return CommandHandle(pid, self)

    def _collect(
        self,
        path: str,
        body: Mapping[str, object],
        on_stdout: OutputHandler | None,
        on_stderr: OutputHandler | None,
        check: bool,
    ) -> CommandResult:
        collector = _OutputCollector(on_stdout, on_stderr)
        for event in self._transport().iter_events("POST", path, json_body=body):
            collector.add(event)
        result = collector.result()
        if check and result.exit_code != 0:
            raise CommandExitError(result)
        return result


class AsyncCommandHandle:
    def __init__(self, pid: int, commands: AsyncCommands) -> None:
        self.pid = pid
        self._commands = commands

    async def wait(
        self,
        *,
        timeout: float | None = 60,
        on_stdout: AsyncOutputHandler | None = None,
        on_stderr: AsyncOutputHandler | None = None,
        check: bool = True,
    ) -> CommandResult:
        return await self._commands._collect(
            "/envd/process/connect",
            {"pid": self.pid, "timeout": timeout},
            on_stdout,
            on_stderr,
            check,
        )

    async def send_stdin(self, data: str | bytes) -> None:
        await self._commands.send_stdin(self.pid, data)

    async def close_stdin(self) -> None:
        await self._commands.close_stdin(self.pid)

    async def send_signal(self, signal: str) -> None:
        await self._commands.send_signal(self.pid, signal)

    async def kill(self) -> None:
        await self.send_signal("SIGKILL")


class AsyncCommands:
    def __init__(self, transport: AsyncTransportProvider) -> None:
        self._transport = transport

    async def run(
        self,
        command: str,
        *,
        background: bool = False,
        envs: Mapping[str, str] | None = None,
        cwd: str | None = None,
        user: str | None = None,
        stdin: bool = False,
        timeout: float | None = 60,
        on_stdout: AsyncOutputHandler | None = None,
        on_stderr: AsyncOutputHandler | None = None,
        check: bool = True,
    ) -> CommandResult | AsyncCommandHandle:
        body = _command_body(command, envs, cwd, user, stdin, timeout)
        if background:
            return await self._start_background(body)
        return await self._collect("/envd/process/start", body, on_stdout, on_stderr, check)

    def connect(self, pid: int) -> AsyncCommandHandle:
        _validate_pid(pid)
        return AsyncCommandHandle(pid, self)

    async def list(self) -> tuple[ProcessInfo, ...]:
        transport = await self._transport()
        payload = await transport.request("POST", "/envd/process/list", json_body={})
        values = _list_payload(payload, "processes")
        return tuple(ProcessInfo.from_wire(item) for item in values)

    async def send_stdin(self, pid: int, data: str | bytes) -> None:
        _validate_pid(pid)
        transport = await self._transport()
        await transport.request(
            "POST",
            "/envd/process/send-input",
            json_body={"pid": pid, "data": _input(data)},
        )

    async def close_stdin(self, pid: int) -> None:
        _validate_pid(pid)
        transport = await self._transport()
        await transport.request("POST", "/envd/process/close-stdin", json_body={"pid": pid})

    async def send_signal(self, pid: int, signal: str) -> None:
        _validate_pid(pid)
        transport = await self._transport()
        await transport.request(
            "POST",
            "/envd/process/send-signal",
            json_body={"pid": pid, "signal": signal},
        )

    async def _start_background(
        self, body: Mapping[str, object], pty: PtySize | None = None
    ) -> AsyncCommandHandle:
        request = dict(body)
        request["background"] = True
        if pty:
            request["pty"] = {"rows": pty.rows, "cols": pty.cols}
        transport = await self._transport()
        payload = await transport.request("POST", "/envd/process/start", json_body=request)
        return AsyncCommandHandle(_pid(payload), self)

    async def _collect(
        self,
        path: str,
        body: Mapping[str, object],
        on_stdout: AsyncOutputHandler | None,
        on_stderr: AsyncOutputHandler | None,
        check: bool,
    ) -> CommandResult:
        collector = _OutputCollector()
        transport = await self._transport()
        async for event in transport.iter_events("POST", path, json_body=body):
            chunk = collector.add(event)
            if chunk and chunk.stream == "stdout" and on_stdout:
                await _invoke(on_stdout, chunk.data)
            if chunk and chunk.stream == "stderr" and on_stderr:
                await _invoke(on_stderr, chunk.data)
        result = collector.result()
        if check and result.exit_code != 0:
            raise CommandExitError(result)
        return result


class _OutputCollector:
    def __init__(
        self,
        on_stdout: OutputHandler | None = None,
        on_stderr: OutputHandler | None = None,
    ) -> None:
        self._stdout: list[str] = []
        self._stderr: list[str] = []
        self._exit_code: int | None = None
        self._pid: int | None = None
        self._on_stdout = on_stdout
        self._on_stderr = on_stderr

    def add(self, event: Mapping[str, Any]) -> OutputChunk | None:
        event_type = str(event.get("type", event.get("stream", ""))).lower()
        if "pid" in event:
            self._pid = int(event["pid"])
        if "exitCode" in event or "exit_code" in event:
            self._exit_code = int(event.get("exitCode", event.get("exit_code", 0)))
        if "stdout" in event and event_type not in {"stdout", "stderr"}:
            self._append("stdout", str(event["stdout"]))
        if "stderr" in event and event_type not in {"stdout", "stderr"}:
            self._append("stderr", str(event["stderr"]))
        if event_type not in {"stdout", "stderr"}:
            return None
        data = str(event.get("data", event.get(event_type, "")))
        self._append(event_type, data)
        return OutputChunk(
            stream=event_type,
            data=data,
            timestamp=parse_optional_datetime(event.get("timestamp")),
        )

    def result(self) -> CommandResult:
        if self._exit_code is None:
            raise ProtocolError("command stream ended without an exit status")
        return CommandResult(
            exit_code=self._exit_code,
            stdout="".join(self._stdout),
            stderr="".join(self._stderr),
            pid=self._pid,
        )

    def _append(self, stream: str, data: str) -> None:
        if stream == "stdout":
            self._stdout.append(data)
            if self._on_stdout:
                self._on_stdout(data)
        else:
            self._stderr.append(data)
            if self._on_stderr:
                self._on_stderr(data)


def _command_body(
    command: str,
    envs: Mapping[str, str] | None,
    cwd: str | None,
    user: str | None,
    stdin: bool,
    timeout: float | None,
) -> dict[str, object]:
    if not command.strip():
        raise ValueError("command must not be blank")
    if timeout is not None and timeout < 0:
        raise ValueError("timeout must be non-negative or None")
    body: dict[str, object] = {
        "command": command,
        "envs": dict(envs or {}),
        "stdin": stdin,
        "timeout": timeout,
    }
    if cwd:
        body["cwd"] = cwd
    if user:
        body["user"] = user
    return body


def _pid(payload: object) -> int:
    if not isinstance(payload, Mapping) or "pid" not in payload:
        raise ProtocolError("process response does not contain pid")
    pid = int(payload["pid"])
    _validate_pid(pid)
    return pid


def _validate_pid(pid: int) -> None:
    if pid < 1:
        raise ValueError("pid must be positive")


def _input(data: str | bytes) -> str:
    return data.decode() if isinstance(data, bytes) else data


def _list_payload(payload: object, key: str) -> tuple[Mapping[str, Any], ...]:
    if isinstance(payload, list):
        source = payload
    elif isinstance(payload, Mapping):
        source = payload.get(key, payload.get("items", []))
    else:
        source = []
    if not isinstance(source, list):
        raise ProtocolError("process response is invalid")
    return tuple(item for item in source if isinstance(item, Mapping))


async def _invoke(handler: AsyncOutputHandler, value: str) -> None:
    result = handler(value)
    if inspect.isawaitable(result):
        await result
