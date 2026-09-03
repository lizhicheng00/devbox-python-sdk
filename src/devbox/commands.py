from __future__ import annotations

import base64
import codecs
import inspect
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator, Mapping
from typing import Any, Literal, overload

from ._transport import AsyncTransport, SyncTransport
from .errors import CommandExitError, ProtocolError
from .models import CommandResult, OutputChunk, ProcessInfo, PtySize

OutputHandler = Callable[[str], None]
AsyncOutputHandler = Callable[[str], Awaitable[None] | None]
SyncTransportProvider = Callable[[], SyncTransport]
AsyncTransportProvider = Callable[[], Awaitable[AsyncTransport]]

_PROCESS = "/process.Process"


class CommandHandle:
    def __init__(
        self,
        pid: int,
        commands: Commands,
        events: Iterator[Mapping[str, Any]] | None = None,
        *,
        input_stream: str = "stdin",
    ) -> None:
        self.pid = pid
        self._commands = commands
        self._events = events
        self._input_stream = input_stream
        self._result: CommandResult | None = None

    def wait(
        self,
        *,
        on_stdout: OutputHandler | None = None,
        on_stderr: OutputHandler | None = None,
        check: bool = True,
    ) -> CommandResult:
        """Wait for completion and collect the command output."""
        if self._result is None:
            events = self._events or self._commands._connect_events(self.pid, 60)
            self._events = None
            self._result = self._commands._collect_events(events, self.pid, on_stdout, on_stderr)
        if check and self._result.exit_code != 0:
            raise CommandExitError(self._result)
        return self._result

    def send_stdin(self, data: str | bytes) -> None:
        self._commands._send_input(self.pid, data, self._input_stream)

    def close_stdin(self) -> None:
        self._commands.close_stdin(self.pid)

    def send_signal(self, signal: str) -> None:
        self._commands.send_signal(self.pid, signal)

    def kill(self) -> None:
        self.send_signal("SIGKILL")

    def disconnect(self) -> None:
        close = getattr(self._events, "close", None)
        if close:
            close()
        self._events = None


class Commands:
    """Run and manage processes inside a sandbox."""

    def __init__(self, transport: SyncTransportProvider) -> None:
        self._transport = transport

    @overload
    def run(
        self,
        command: str,
        *,
        background: Literal[False] = False,
        envs: Mapping[str, str] | None = None,
        cwd: str | None = None,
        user: str | None = None,
        stdin: bool = False,
        timeout: float | None = 60,
        on_stdout: OutputHandler | None = None,
        on_stderr: OutputHandler | None = None,
        check: bool = True,
    ) -> CommandResult: ...

    @overload
    def run(
        self,
        command: str,
        *,
        background: Literal[True],
        envs: Mapping[str, str] | None = None,
        cwd: str | None = None,
        user: str | None = None,
        stdin: bool = False,
        timeout: float | None = 60,
        on_stdout: None = None,
        on_stderr: None = None,
        check: bool = True,
    ) -> CommandHandle: ...

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
        """Run a shell command or return a handle for a background command."""
        if background and (on_stdout is not None or on_stderr is not None):
            raise ValueError("background output callbacks belong on handle.wait()")
        handle = self._start(_command_body(command, envs, cwd, stdin), timeout=timeout, user=user)
        if background:
            return handle
        return handle.wait(on_stdout=on_stdout, on_stderr=on_stderr, check=check)

    def connect(self, pid: int, *, timeout: float | None = 60) -> CommandHandle:
        _validate_pid(pid)
        return CommandHandle(pid, self, self._connect_events(pid, timeout))

    def list(self) -> tuple[ProcessInfo, ...]:
        payload = self._transport().connect_unary(f"{_PROCESS}/List", {})
        return tuple(ProcessInfo.from_wire(item) for item in _items(payload, "processes"))

    def send_stdin(self, pid: int, data: str | bytes) -> None:
        self._send_input(pid, data, "stdin")

    def close_stdin(self, pid: int) -> None:
        _validate_pid(pid)
        self._transport().connect_unary(f"{_PROCESS}/CloseStdin", {"process": {"pid": pid}})

    def send_signal(self, pid: int, signal: str) -> None:
        _validate_pid(pid)
        self._transport().connect_unary(
            f"{_PROCESS}/SendSignal",
            {"process": {"pid": pid}, "signal": _signal(signal)},
        )

    def _start(
        self,
        body: Mapping[str, object],
        *,
        timeout: float | None,
        user: str | None = None,
        pty: PtySize | None = None,
        input_stream: str = "stdin",
    ) -> CommandHandle:
        request = dict(body)
        if pty:
            request["pty"] = {"size": {"rows": pty.rows, "cols": pty.cols}}
        events = self._transport().connect_stream(
            f"{_PROCESS}/Start",
            request,
            timeout=timeout,
            headers=_process_headers(user),
        )
        pid = _first_pid(events, "start process")
        return CommandHandle(pid, self, events, input_stream=input_stream)

    def _connect_events(self, pid: int, timeout: float | None) -> Iterator[Mapping[str, Any]]:
        events = self._transport().connect_stream(
            f"{_PROCESS}/Connect",
            {"process": {"pid": pid}},
            timeout=timeout,
            headers={"Keepalive-Ping-Interval": "50"},
        )
        connected_pid = _first_pid(events, "connect to process")
        if connected_pid != pid:
            raise ProtocolError("EnvD connected to an unexpected process")
        return events

    def _send_input(self, pid: int, data: str | bytes, stream: str) -> None:
        _validate_pid(pid)
        self._transport().connect_unary(
            f"{_PROCESS}/SendInput",
            {
                "process": {"pid": pid},
                "input": {stream: base64.b64encode(_bytes(data)).decode("ascii")},
            },
        )

    @staticmethod
    def _collect_events(
        events: Iterator[Mapping[str, Any]],
        pid: int,
        on_stdout: OutputHandler | None,
        on_stderr: OutputHandler | None,
    ) -> CommandResult:
        collector = _OutputCollector(pid, on_stdout, on_stderr)
        for event in events:
            collector.add(event)
        return collector.result()


class AsyncCommandHandle:
    def __init__(
        self,
        pid: int,
        commands: AsyncCommands,
        events: AsyncIterator[Mapping[str, Any]] | None = None,
        *,
        input_stream: str = "stdin",
    ) -> None:
        self.pid = pid
        self._commands = commands
        self._events = events
        self._input_stream = input_stream
        self._result: CommandResult | None = None

    async def wait(
        self,
        *,
        on_stdout: AsyncOutputHandler | None = None,
        on_stderr: AsyncOutputHandler | None = None,
        check: bool = True,
    ) -> CommandResult:
        if self._result is None:
            events = self._events or await self._commands._connect_events(self.pid, 60)
            self._events = None
            self._result = await self._commands._collect_events(
                events, self.pid, on_stdout, on_stderr
            )
        if check and self._result.exit_code != 0:
            raise CommandExitError(self._result)
        return self._result

    async def send_stdin(self, data: str | bytes) -> None:
        await self._commands._send_input(self.pid, data, self._input_stream)

    async def close_stdin(self) -> None:
        await self._commands.close_stdin(self.pid)

    async def send_signal(self, signal: str) -> None:
        await self._commands.send_signal(self.pid, signal)

    async def kill(self) -> None:
        await self.send_signal("SIGKILL")

    async def disconnect(self) -> None:
        close = getattr(self._events, "aclose", None)
        if close:
            await close()
        self._events = None


class AsyncCommands:
    """Run and manage processes through the asynchronous API."""

    def __init__(self, transport: AsyncTransportProvider) -> None:
        self._transport = transport

    @overload
    async def run(
        self,
        command: str,
        *,
        background: Literal[False] = False,
        envs: Mapping[str, str] | None = None,
        cwd: str | None = None,
        user: str | None = None,
        stdin: bool = False,
        timeout: float | None = 60,
        on_stdout: AsyncOutputHandler | None = None,
        on_stderr: AsyncOutputHandler | None = None,
        check: bool = True,
    ) -> CommandResult: ...

    @overload
    async def run(
        self,
        command: str,
        *,
        background: Literal[True],
        envs: Mapping[str, str] | None = None,
        cwd: str | None = None,
        user: str | None = None,
        stdin: bool = False,
        timeout: float | None = 60,
        on_stdout: None = None,
        on_stderr: None = None,
        check: bool = True,
    ) -> AsyncCommandHandle: ...

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
        """Run a shell command or return a handle for a background command."""
        if background and (on_stdout is not None or on_stderr is not None):
            raise ValueError("background output callbacks belong on handle.wait()")
        handle = await self._start(
            _command_body(command, envs, cwd, stdin), timeout=timeout, user=user
        )
        if background:
            return handle
        return await handle.wait(on_stdout=on_stdout, on_stderr=on_stderr, check=check)

    async def connect(self, pid: int, *, timeout: float | None = 60) -> AsyncCommandHandle:
        _validate_pid(pid)
        return AsyncCommandHandle(pid, self, await self._connect_events(pid, timeout))

    async def list(self) -> tuple[ProcessInfo, ...]:
        transport = await self._transport()
        payload = await transport.connect_unary(f"{_PROCESS}/List", {})
        return tuple(ProcessInfo.from_wire(item) for item in _items(payload, "processes"))

    async def send_stdin(self, pid: int, data: str | bytes) -> None:
        await self._send_input(pid, data, "stdin")

    async def close_stdin(self, pid: int) -> None:
        _validate_pid(pid)
        transport = await self._transport()
        await transport.connect_unary(f"{_PROCESS}/CloseStdin", {"process": {"pid": pid}})

    async def send_signal(self, pid: int, signal: str) -> None:
        _validate_pid(pid)
        transport = await self._transport()
        await transport.connect_unary(
            f"{_PROCESS}/SendSignal",
            {"process": {"pid": pid}, "signal": _signal(signal)},
        )

    async def _start(
        self,
        body: Mapping[str, object],
        *,
        timeout: float | None,
        user: str | None = None,
        pty: PtySize | None = None,
        input_stream: str = "stdin",
    ) -> AsyncCommandHandle:
        request = dict(body)
        if pty:
            request["pty"] = {"size": {"rows": pty.rows, "cols": pty.cols}}
        transport = await self._transport()
        events = transport.connect_stream(
            f"{_PROCESS}/Start",
            request,
            timeout=timeout,
            headers=_process_headers(user),
        )
        pid = await _first_pid_async(events, "start process")
        return AsyncCommandHandle(pid, self, events, input_stream=input_stream)

    async def _connect_events(
        self, pid: int, timeout: float | None
    ) -> AsyncIterator[Mapping[str, Any]]:
        transport = await self._transport()
        events = transport.connect_stream(
            f"{_PROCESS}/Connect",
            {"process": {"pid": pid}},
            timeout=timeout,
            headers={"Keepalive-Ping-Interval": "50"},
        )
        connected_pid = await _first_pid_async(events, "connect to process")
        if connected_pid != pid:
            raise ProtocolError("EnvD connected to an unexpected process")
        return events

    async def _send_input(self, pid: int, data: str | bytes, stream: str) -> None:
        _validate_pid(pid)
        transport = await self._transport()
        await transport.connect_unary(
            f"{_PROCESS}/SendInput",
            {
                "process": {"pid": pid},
                "input": {stream: base64.b64encode(_bytes(data)).decode("ascii")},
            },
        )

    @staticmethod
    async def _collect_events(
        events: AsyncIterator[Mapping[str, Any]],
        pid: int,
        on_stdout: AsyncOutputHandler | None,
        on_stderr: AsyncOutputHandler | None,
    ) -> CommandResult:
        collector = _OutputCollector(pid)
        async for event in events:
            chunk = collector.add(event)
            if chunk and chunk.stream == "stdout" and on_stdout:
                await _invoke(on_stdout, chunk.data)
            if chunk and chunk.stream == "stderr" and on_stderr:
                await _invoke(on_stderr, chunk.data)
        return collector.result()


class _OutputCollector:
    def __init__(
        self,
        pid: int,
        on_stdout: OutputHandler | None = None,
        on_stderr: OutputHandler | None = None,
    ) -> None:
        self._pid = pid
        self._stdout: list[str] = []
        self._stderr: list[str] = []
        self._exit_code: int | None = None
        self._stdout_decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._stderr_decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._on_stdout = on_stdout
        self._on_stderr = on_stderr

    def add(self, response: Mapping[str, Any]) -> OutputChunk | None:
        event = response.get("event")
        if not isinstance(event, Mapping):
            return None
        data = event.get("data")
        if isinstance(data, Mapping):
            for stream in ("stdout", "stderr", "pty"):
                if stream in data:
                    target = "stdout" if stream == "pty" else stream
                    value = self._decode(target, data[stream])
                    if value:
                        self._append(target, value)
                        return OutputChunk(stream=target, data=value)
        end = event.get("end")
        if isinstance(end, Mapping):
            self._exit_code = int(end.get("exitCode", end.get("exit_code", 0)))
        return None

    def result(self) -> CommandResult:
        self._flush()
        if self._exit_code is None:
            raise ProtocolError("command stream ended without an exit status")
        return CommandResult(
            exit_code=self._exit_code,
            stdout="".join(self._stdout),
            stderr="".join(self._stderr),
            pid=self._pid,
        )

    def _decode(self, stream: str, value: object) -> str:
        try:
            data = base64.b64decode(str(value), validate=True)
        except ValueError as error:
            raise ProtocolError("EnvD returned invalid process output") from error
        decoder = self._stdout_decoder if stream == "stdout" else self._stderr_decoder
        return decoder.decode(data)

    def _flush(self) -> None:
        stdout = self._stdout_decoder.decode(b"", final=True)
        stderr = self._stderr_decoder.decode(b"", final=True)
        if stdout:
            self._append("stdout", stdout)
        if stderr:
            self._append("stderr", stderr)

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
    stdin: bool,
) -> dict[str, object]:
    if not command.strip():
        raise ValueError("command must not be blank")
    process: dict[str, object] = {
        "cmd": "/bin/bash",
        "args": ["-l", "-c", command],
        "envs": dict(envs or {}),
    }
    if cwd:
        process["cwd"] = cwd
    return {"process": process, "stdin": stdin}


def _process_headers(user: str | None) -> dict[str, str]:
    headers = {"Keepalive-Ping-Interval": "50"}
    if user:
        token = base64.b64encode(f"{user}:".encode()).decode("ascii")
        headers["Authorization"] = f"Basic {token}"
    return headers


def _first_pid(events: Iterator[Mapping[str, Any]], action: str) -> int:
    try:
        response = next(events)
    except StopIteration as error:
        raise ProtocolError(f"EnvD did not {action}") from error
    return _start_pid(response, action)


async def _first_pid_async(events: AsyncIterator[Mapping[str, Any]], action: str) -> int:
    try:
        response = await anext(events)
    except StopAsyncIteration as error:
        raise ProtocolError(f"EnvD did not {action}") from error
    return _start_pid(response, action)


def _start_pid(response: Mapping[str, Any], action: str) -> int:
    event = response.get("event")
    start = event.get("start") if isinstance(event, Mapping) else None
    if not isinstance(start, Mapping) or "pid" not in start:
        raise ProtocolError(f"EnvD did not {action}")
    pid = int(start["pid"])
    _validate_pid(pid)
    return pid


def _items(payload: object, key: str) -> tuple[Mapping[str, Any], ...]:
    source = payload.get(key, []) if isinstance(payload, Mapping) else []
    if not isinstance(source, list):
        raise ProtocolError("process response is invalid")
    return tuple(item for item in source if isinstance(item, Mapping))


def _signal(value: str) -> str:
    normalized = value.upper()
    if normalized.startswith("SIGNAL_"):
        return normalized
    if normalized in {"SIGTERM", "SIGKILL"}:
        return f"SIGNAL_{normalized}"
    raise ValueError("signal must be SIGTERM or SIGKILL")


def _bytes(value: str | bytes) -> bytes:
    return value.encode() if isinstance(value, str) else value


def _validate_pid(pid: int) -> None:
    if pid < 1:
        raise ValueError("pid must be positive")


async def _invoke(handler: AsyncOutputHandler, value: str) -> None:
    result = handler(value)
    if inspect.isawaitable(result):
        await result
