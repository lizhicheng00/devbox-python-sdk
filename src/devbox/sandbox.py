from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from types import TracebackType
from typing import Any
from urllib.parse import quote
from uuid import uuid4

from ._transport import AsyncTransport, SyncTransport
from .commands import AsyncCommands, Commands
from .config import ConnectionConfig
from .errors import DevBoxError, ErrorDetail, NotFoundError, ProtocolError
from .filesystem import AsyncFilesystem, Filesystem
from .git import AsyncGit, Git
from .models import (
    LogLevel,
    LogsDirection,
    NetworkConfig,
    Page,
    SandboxConnection,
    SandboxInfo,
    SandboxLogEntry,
    SandboxMetrics,
    SandboxState,
    SnapshotInfo,
    VolumeMount,
)
from .pty import AsyncPty, Pty


class Sandboxes:
    """Sandbox lifecycle operations bound to a reusable client."""

    def __init__(
        self,
        transport: SyncTransport,
        request_timeout: float = 30.0,
        *,
        gateway_url: str | None = None,
    ) -> None:
        self._transport = transport
        self._request_timeout = request_timeout
        self._gateway_url = gateway_url

    def create(
        self,
        template: str = "default",
        *,
        timeout: int = 300,
        envs: Mapping[str, str] | None = None,
        metadata: Mapping[str, str] | None = None,
        network: NetworkConfig | None = None,
        auto_pause: bool = False,
        auto_pause_memory: bool = True,
        auto_resume: bool = False,
        secure: bool = True,
        client_id: str | None = None,
        build_id: str | None = None,
        volume_mounts: Sequence[VolumeMount] = (),
        idempotency_key: str | None = None,
    ) -> Sandbox:
        payload = self._transport.request(
            "POST",
            "/sandboxes",
            json_body=_create_body(
                template,
                timeout,
                envs,
                metadata,
                network,
                auto_pause,
                auto_pause_memory,
                auto_resume,
                secure,
                client_id,
                build_id,
                volume_mounts,
            ),
            headers={"Idempotency-Key": idempotency_key or str(uuid4())},
        )
        info, connection = _sandbox_payload(payload)
        return Sandbox(
            self._transport,
            info,
            connection,
            request_timeout=self._request_timeout,
            gateway_url=self._gateway_url,
        )

    def connect(self, sandbox_id: str, *, timeout: int = 300) -> Sandbox:
        payload = self._transport.request(
            "POST",
            f"/sandboxes/{_id(sandbox_id)}/connect",
            json_body={"timeout": _checked_timeout(timeout)},
        )
        info, connection = _sandbox_payload(payload)
        return Sandbox(
            self._transport,
            info,
            connection,
            request_timeout=self._request_timeout,
            gateway_url=self._gateway_url,
        )

    def get(self, sandbox_id: str) -> SandboxInfo:
        return SandboxInfo.from_wire(
            _mapping(self._transport.request("GET", f"/sandboxes/{_id(sandbox_id)}"))
        )

    def list(
        self,
        *,
        metadata: str | None = None,
        states: Sequence[SandboxState | str] = (),
        limit: int | None = None,
        next_token: str | None = None,
    ) -> Page[SandboxInfo]:
        payload, headers = self._transport.request_with_headers(
            "GET", "/v2/sandboxes", params=_list_params(metadata, states, limit, next_token)
        )
        return _sandbox_page(payload, headers.get("X-Next-Token"), headers.get("X-Total-Running"))

    def metrics(self, sandbox_ids: Sequence[str]) -> Mapping[str, SandboxMetrics]:
        payload = _mapping(
            self._transport.request(
                "GET",
                "/sandboxes/metrics",
                params={"sandbox_ids": ",".join(_sandbox_ids(sandbox_ids))},
            )
        )
        values = _mapping(payload.get("sandboxes", {}))
        return {
            str(key): SandboxMetrics.from_wire(_mapping(value)) for key, value in values.items()
        }


class AsyncSandboxes:
    """Asynchronous sandbox lifecycle operations bound to a reusable client."""

    def __init__(
        self,
        transport: AsyncTransport,
        request_timeout: float = 30.0,
        *,
        gateway_url: str | None = None,
    ) -> None:
        self._transport = transport
        self._request_timeout = request_timeout
        self._gateway_url = gateway_url

    async def create(
        self,
        template: str = "default",
        *,
        timeout: int = 300,
        envs: Mapping[str, str] | None = None,
        metadata: Mapping[str, str] | None = None,
        network: NetworkConfig | None = None,
        auto_pause: bool = False,
        auto_pause_memory: bool = True,
        auto_resume: bool = False,
        secure: bool = True,
        client_id: str | None = None,
        build_id: str | None = None,
        volume_mounts: Sequence[VolumeMount] = (),
        idempotency_key: str | None = None,
    ) -> AsyncSandbox:
        payload = await self._transport.request(
            "POST",
            "/sandboxes",
            json_body=_create_body(
                template,
                timeout,
                envs,
                metadata,
                network,
                auto_pause,
                auto_pause_memory,
                auto_resume,
                secure,
                client_id,
                build_id,
                volume_mounts,
            ),
            headers={"Idempotency-Key": idempotency_key or str(uuid4())},
        )
        info, connection = _sandbox_payload(payload)
        return AsyncSandbox(
            self._transport,
            info,
            connection,
            request_timeout=self._request_timeout,
            gateway_url=self._gateway_url,
        )

    async def connect(self, sandbox_id: str, *, timeout: int = 300) -> AsyncSandbox:
        payload = await self._transport.request(
            "POST",
            f"/sandboxes/{_id(sandbox_id)}/connect",
            json_body={"timeout": _checked_timeout(timeout)},
        )
        info, connection = _sandbox_payload(payload)
        return AsyncSandbox(
            self._transport,
            info,
            connection,
            request_timeout=self._request_timeout,
            gateway_url=self._gateway_url,
        )

    async def get(self, sandbox_id: str) -> SandboxInfo:
        return SandboxInfo.from_wire(
            _mapping(await self._transport.request("GET", f"/sandboxes/{_id(sandbox_id)}"))
        )

    async def list(
        self,
        *,
        metadata: str | None = None,
        states: Sequence[SandboxState | str] = (),
        limit: int | None = None,
        next_token: str | None = None,
    ) -> Page[SandboxInfo]:
        payload, headers = await self._transport.request_with_headers(
            "GET", "/v2/sandboxes", params=_list_params(metadata, states, limit, next_token)
        )
        return _sandbox_page(payload, headers.get("X-Next-Token"), headers.get("X-Total-Running"))

    async def metrics(self, sandbox_ids: Sequence[str]) -> Mapping[str, SandboxMetrics]:
        payload = _mapping(
            await self._transport.request(
                "GET",
                "/sandboxes/metrics",
                params={"sandbox_ids": ",".join(_sandbox_ids(sandbox_ids))},
            )
        )
        values = _mapping(payload.get("sandboxes", {}))
        return {
            str(key): SandboxMetrics.from_wire(_mapping(value)) for key, value in values.items()
        }


class Snapshots:
    def __init__(self, transport: SyncTransport) -> None:
        self._transport = transport

    def list(
        self,
        *,
        sandbox_id: str | None = None,
        name: str | None = None,
        limit: int | None = None,
        next_token: str | None = None,
    ) -> Page[SnapshotInfo]:
        payload, headers = self._transport.request_with_headers(
            "GET", "/snapshots", params=_snapshot_params(sandbox_id, name, limit, next_token)
        )
        return _snapshot_page(payload, headers.get("X-Next-Token"))


class AsyncSnapshots:
    def __init__(self, transport: AsyncTransport) -> None:
        self._transport = transport

    async def list(
        self,
        *,
        sandbox_id: str | None = None,
        name: str | None = None,
        limit: int | None = None,
        next_token: str | None = None,
    ) -> Page[SnapshotInfo]:
        payload, headers = await self._transport.request_with_headers(
            "GET", "/snapshots", params=_snapshot_params(sandbox_id, name, limit, next_token)
        )
        return _snapshot_page(payload, headers.get("X-Next-Token"))


class Sandbox:
    """A synchronous remote sandbox.

    Exiting its context manager deletes the remote sandbox. Call ``close()``
    directly when only local connections should be released.
    """

    def __init__(
        self,
        control: SyncTransport,
        info: SandboxInfo,
        connection: SandboxConnection,
        *,
        owns_control: bool = False,
        request_timeout: float = 30.0,
        gateway_url: str | None = None,
    ) -> None:
        self._control = control
        self._info = info
        self._connection = connection
        self._owns_control = owns_control
        self._request_timeout = request_timeout
        self._gateway_url_override = gateway_url
        self._gateway: SyncTransport | None = None
        self.commands = Commands(self._gateway_transport)
        self.files = Filesystem(self._gateway_transport)
        self.pty = Pty(self.commands, self._gateway_transport)
        self.git = Git(self.commands)

    @classmethod
    def create(
        cls,
        template: str = "default",
        *,
        timeout: int = 300,
        envs: Mapping[str, str] | None = None,
        metadata: Mapping[str, str] | None = None,
        network: NetworkConfig | None = None,
        auto_pause: bool = False,
        auto_pause_memory: bool = True,
        auto_resume: bool = False,
        secure: bool = True,
        client_id: str | None = None,
        build_id: str | None = None,
        volume_mounts: Sequence[VolumeMount] = (),
        idempotency_key: str | None = None,
        api_key: str | None = None,
        api_url: str | None = None,
        gateway_url: str | None = None,
        request_timeout: float = 30.0,
        headers: Mapping[str, str] | None = None,
    ) -> Sandbox:
        """Create a sandbox and connect its runtime APIs."""
        config, transport = _sync_control(
            api_key,
            api_url,
            gateway_url,
            request_timeout,
            headers,
        )
        try:
            sandbox = Sandboxes(
                transport,
                config.request_timeout,
                gateway_url=config.gateway_url,
            ).create(
                template,
                timeout=timeout,
                envs=envs,
                metadata=metadata,
                network=network,
                auto_pause=auto_pause,
                auto_pause_memory=auto_pause_memory,
                auto_resume=auto_resume,
                secure=secure,
                client_id=client_id,
                build_id=build_id,
                volume_mounts=volume_mounts,
                idempotency_key=idempotency_key,
            )
        except Exception:
            transport.close()
            raise
        sandbox._owns_control = True
        return sandbox

    @classmethod
    def connect(
        cls,
        sandbox_id: str,
        *,
        timeout: int = 300,
        api_key: str | None = None,
        api_url: str | None = None,
        gateway_url: str | None = None,
        request_timeout: float = 30.0,
        headers: Mapping[str, str] | None = None,
    ) -> Sandbox:
        """Connect to an existing sandbox, resuming it when necessary."""
        config, transport = _sync_control(
            api_key,
            api_url,
            gateway_url,
            request_timeout,
            headers,
        )
        try:
            sandbox = Sandboxes(
                transport,
                config.request_timeout,
                gateway_url=config.gateway_url,
            ).connect(sandbox_id, timeout=timeout)
        except Exception:
            transport.close()
            raise
        sandbox._owns_control = True
        return sandbox

    @property
    def sandbox_id(self) -> str:
        return self._info.sandbox_id

    @property
    def info(self) -> SandboxInfo:
        return self._info

    def get_info(self) -> SandboxInfo:
        self._info = SandboxInfo.from_wire(
            _mapping(self._control.request("GET", f"/sandboxes/{_id(self.sandbox_id)}"))
        )
        return self._info

    def is_running(self) -> bool:
        """Return whether the Manager reports the sandbox as running."""
        try:
            return self.get_info().state is SandboxState.RUNNING
        except NotFoundError:
            self._info = replace(self._info, state=SandboxState.STOPPED)
            return False

    def pause(self, *, memory: bool = True) -> None:
        self._control.request(
            "POST", f"/sandboxes/{_id(self.sandbox_id)}/pause", json_body={"memory": memory}
        )
        self._info = replace(self._info, state=SandboxState.PAUSED)
        self._close_gateway()

    def resume(self, *, timeout: int = 300) -> None:
        self._apply_connection(
            self._control.request(
                "POST",
                f"/sandboxes/{_id(self.sandbox_id)}/connect",
                json_body={"timeout": _checked_timeout(timeout)},
            )
        )

    def set_timeout(self, timeout: int) -> None:
        self._control.request(
            "POST",
            f"/sandboxes/{_id(self.sandbox_id)}/timeout",
            json_body={"timeout": _checked_timeout(timeout)},
        )

    def refresh(self, duration: int = 300) -> None:
        self._control.request(
            "POST",
            f"/sandboxes/{_id(self.sandbox_id)}/refreshes",
            json_body={"duration": _checked_timeout(duration)},
        )

    def kill(self) -> bool:
        """Delete the sandbox, returning whether it still existed."""
        try:
            self._control.request("DELETE", f"/sandboxes/{_id(self.sandbox_id)}")
        except NotFoundError:
            self._info = replace(self._info, state=SandboxState.STOPPED)
            return False
        finally:
            self._close_gateway()
        self._info = replace(self._info, state=SandboxState.STOPPED)
        return True

    def snapshot(self, name: str | None = None) -> SnapshotInfo:
        payload = self._control.request(
            "POST",
            f"/sandboxes/{_id(self.sandbox_id)}/snapshots",
            json_body={"name": name} if name else {},
        )
        return SnapshotInfo.from_wire(_mapping(payload))

    def fork(self, *, timeout: int = 300, count: int = 1) -> tuple[SandboxForkResult, ...]:
        payload = self._control.request(
            "POST",
            f"/sandboxes/{_id(self.sandbox_id)}/fork",
            json_body=_fork_body(timeout, count),
        )
        return tuple(
            _fork_result(
                item,
                self._control,
                self._request_timeout,
                self._gateway_url_override,
            )
            for item in _items(payload)
        )

    def get_logs(
        self,
        *,
        cursor: int | None = None,
        limit: int = 1000,
        direction: LogsDirection | str | None = None,
        level: LogLevel | str | None = None,
        search: str | None = None,
    ) -> tuple[SandboxLogEntry, ...]:
        payload = _mapping(
            self._control.request(
                "GET",
                f"/v2/sandboxes/{_id(self.sandbox_id)}/logs",
                params=_log_params(cursor, limit, direction, level, search),
            )
        )
        return tuple(SandboxLogEntry.from_wire(item) for item in _items(payload.get("logs", [])))

    def get_metrics(
        self, *, start: int | datetime | None = None, end: int | datetime | None = None
    ) -> tuple[SandboxMetrics, ...]:
        payload = self._control.request(
            "GET", f"/sandboxes/{_id(self.sandbox_id)}/metrics", params=_metric_params(start, end)
        )
        return tuple(SandboxMetrics.from_wire(item) for item in _items(payload))

    def update_network(self, network: NetworkConfig) -> None:
        self._control.request(
            "PUT", f"/sandboxes/{_id(self.sandbox_id)}/network", json_body=network.to_update_wire()
        )

    def close(self) -> None:
        """Close local connections without deleting the remote sandbox."""
        self._close_gateway()
        if self._owns_control:
            self._control.close()

    def __enter__(self) -> Sandbox:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        try:
            self.kill()
        except DevBoxError:
            if exc_type is None:
                raise
        finally:
            self.close()

    def _gateway_transport(self) -> SyncTransport:
        if _expires_soon(self._connection.expires_at):
            self.resume()
        if self._gateway is None:
            self._gateway = SyncTransport(
                _gateway_url(self._connection, self._gateway_url_override),
                headers=_gateway_headers(self._connection),
                timeout=self._request_timeout,
            )
        return self._gateway

    def _apply_connection(self, payload: object) -> None:
        self._info, self._connection = _sandbox_payload(payload)
        self._close_gateway()

    def _close_gateway(self) -> None:
        if self._gateway is not None:
            self._gateway.close()
            self._gateway = None


class AsyncSandbox:
    """An asynchronous remote sandbox with automatic context cleanup."""

    def __init__(
        self,
        control: AsyncTransport,
        info: SandboxInfo,
        connection: SandboxConnection,
        *,
        owns_control: bool = False,
        request_timeout: float = 30.0,
        gateway_url: str | None = None,
    ) -> None:
        self._control = control
        self._info = info
        self._connection = connection
        self._owns_control = owns_control
        self._request_timeout = request_timeout
        self._gateway_url_override = gateway_url
        self._gateway: AsyncTransport | None = None
        self.commands = AsyncCommands(self._gateway_transport)
        self.files = AsyncFilesystem(self._gateway_transport)
        self.pty = AsyncPty(self.commands, self._gateway_transport)
        self.git = AsyncGit(self.commands)

    @classmethod
    async def create(
        cls,
        template: str = "default",
        *,
        timeout: int = 300,
        envs: Mapping[str, str] | None = None,
        metadata: Mapping[str, str] | None = None,
        network: NetworkConfig | None = None,
        auto_pause: bool = False,
        auto_pause_memory: bool = True,
        auto_resume: bool = False,
        secure: bool = True,
        client_id: str | None = None,
        build_id: str | None = None,
        volume_mounts: Sequence[VolumeMount] = (),
        idempotency_key: str | None = None,
        api_key: str | None = None,
        api_url: str | None = None,
        gateway_url: str | None = None,
        request_timeout: float = 30.0,
        headers: Mapping[str, str] | None = None,
    ) -> AsyncSandbox:
        """Create a sandbox and connect its runtime APIs."""
        config, transport = _async_control(
            api_key,
            api_url,
            gateway_url,
            request_timeout,
            headers,
        )
        try:
            sandbox = await AsyncSandboxes(
                transport,
                config.request_timeout,
                gateway_url=config.gateway_url,
            ).create(
                template,
                timeout=timeout,
                envs=envs,
                metadata=metadata,
                network=network,
                auto_pause=auto_pause,
                auto_pause_memory=auto_pause_memory,
                auto_resume=auto_resume,
                secure=secure,
                client_id=client_id,
                build_id=build_id,
                volume_mounts=volume_mounts,
                idempotency_key=idempotency_key,
            )
        except Exception:
            await transport.close()
            raise
        sandbox._owns_control = True
        return sandbox

    @classmethod
    async def connect(
        cls,
        sandbox_id: str,
        *,
        timeout: int = 300,
        api_key: str | None = None,
        api_url: str | None = None,
        gateway_url: str | None = None,
        request_timeout: float = 30.0,
        headers: Mapping[str, str] | None = None,
    ) -> AsyncSandbox:
        """Connect to an existing sandbox, resuming it when necessary."""
        config, transport = _async_control(
            api_key,
            api_url,
            gateway_url,
            request_timeout,
            headers,
        )
        try:
            sandbox = await AsyncSandboxes(
                transport,
                config.request_timeout,
                gateway_url=config.gateway_url,
            ).connect(sandbox_id, timeout=timeout)
        except Exception:
            await transport.close()
            raise
        sandbox._owns_control = True
        return sandbox

    @property
    def sandbox_id(self) -> str:
        return self._info.sandbox_id

    @property
    def info(self) -> SandboxInfo:
        return self._info

    async def get_info(self) -> SandboxInfo:
        self._info = SandboxInfo.from_wire(
            _mapping(await self._control.request("GET", f"/sandboxes/{_id(self.sandbox_id)}"))
        )
        return self._info

    async def is_running(self) -> bool:
        """Return whether the Manager reports the sandbox as running."""
        try:
            return (await self.get_info()).state is SandboxState.RUNNING
        except NotFoundError:
            self._info = replace(self._info, state=SandboxState.STOPPED)
            return False

    async def pause(self, *, memory: bool = True) -> None:
        await self._control.request(
            "POST", f"/sandboxes/{_id(self.sandbox_id)}/pause", json_body={"memory": memory}
        )
        self._info = replace(self._info, state=SandboxState.PAUSED)
        await self._close_gateway()

    async def resume(self, *, timeout: int = 300) -> None:
        await self._apply_connection(
            await self._control.request(
                "POST",
                f"/sandboxes/{_id(self.sandbox_id)}/connect",
                json_body={"timeout": _checked_timeout(timeout)},
            )
        )

    async def set_timeout(self, timeout: int) -> None:
        await self._control.request(
            "POST",
            f"/sandboxes/{_id(self.sandbox_id)}/timeout",
            json_body={"timeout": _checked_timeout(timeout)},
        )

    async def refresh(self, duration: int = 300) -> None:
        await self._control.request(
            "POST",
            f"/sandboxes/{_id(self.sandbox_id)}/refreshes",
            json_body={"duration": _checked_timeout(duration)},
        )

    async def kill(self) -> bool:
        """Delete the sandbox, returning whether it still existed."""
        try:
            await self._control.request("DELETE", f"/sandboxes/{_id(self.sandbox_id)}")
        except NotFoundError:
            self._info = replace(self._info, state=SandboxState.STOPPED)
            return False
        finally:
            await self._close_gateway()
        self._info = replace(self._info, state=SandboxState.STOPPED)
        return True

    async def snapshot(self, name: str | None = None) -> SnapshotInfo:
        payload = await self._control.request(
            "POST",
            f"/sandboxes/{_id(self.sandbox_id)}/snapshots",
            json_body={"name": name} if name else {},
        )
        return SnapshotInfo.from_wire(_mapping(payload))

    async def fork(
        self, *, timeout: int = 300, count: int = 1
    ) -> tuple[AsyncSandboxForkResult, ...]:
        payload = await self._control.request(
            "POST",
            f"/sandboxes/{_id(self.sandbox_id)}/fork",
            json_body=_fork_body(timeout, count),
        )
        return tuple(
            _async_fork_result(
                item,
                self._control,
                self._request_timeout,
                self._gateway_url_override,
            )
            for item in _items(payload)
        )

    async def get_logs(
        self,
        *,
        cursor: int | None = None,
        limit: int = 1000,
        direction: LogsDirection | str | None = None,
        level: LogLevel | str | None = None,
        search: str | None = None,
    ) -> tuple[SandboxLogEntry, ...]:
        payload = _mapping(
            await self._control.request(
                "GET",
                f"/v2/sandboxes/{_id(self.sandbox_id)}/logs",
                params=_log_params(cursor, limit, direction, level, search),
            )
        )
        return tuple(SandboxLogEntry.from_wire(item) for item in _items(payload.get("logs", [])))

    async def get_metrics(
        self, *, start: int | datetime | None = None, end: int | datetime | None = None
    ) -> tuple[SandboxMetrics, ...]:
        payload = await self._control.request(
            "GET", f"/sandboxes/{_id(self.sandbox_id)}/metrics", params=_metric_params(start, end)
        )
        return tuple(SandboxMetrics.from_wire(item) for item in _items(payload))

    async def update_network(self, network: NetworkConfig) -> None:
        await self._control.request(
            "PUT", f"/sandboxes/{_id(self.sandbox_id)}/network", json_body=network.to_update_wire()
        )

    async def close(self) -> None:
        """Close local connections without deleting the remote sandbox."""
        await self._close_gateway()
        if self._owns_control:
            await self._control.close()

    async def __aenter__(self) -> AsyncSandbox:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        try:
            await self.kill()
        except DevBoxError:
            if exc_type is None:
                raise
        finally:
            await self.close()

    async def _gateway_transport(self) -> AsyncTransport:
        if _expires_soon(self._connection.expires_at):
            await self.resume()
        if self._gateway is None:
            self._gateway = AsyncTransport(
                _gateway_url(self._connection, self._gateway_url_override),
                headers=_gateway_headers(self._connection),
                timeout=self._request_timeout,
            )
        return self._gateway

    async def _apply_connection(self, payload: object) -> None:
        self._info, self._connection = _sandbox_payload(payload)
        await self._close_gateway()

    async def _close_gateway(self) -> None:
        if self._gateway is not None:
            await self._gateway.close()
            self._gateway = None


@dataclass(frozen=True, slots=True)
class SandboxForkResult:
    sandbox: Sandbox | None
    error: ErrorDetail | None


@dataclass(frozen=True, slots=True)
class AsyncSandboxForkResult:
    sandbox: AsyncSandbox | None
    error: ErrorDetail | None


def _sync_control(
    api_key: str | None,
    api_url: str | None,
    gateway_url: str | None,
    request_timeout: float,
    headers: Mapping[str, str] | None,
) -> tuple[ConnectionConfig, SyncTransport]:
    config = ConnectionConfig.resolve(
        api_key=api_key,
        api_url=api_url,
        gateway_url=gateway_url,
        request_timeout=request_timeout,
        headers=headers,
    )
    return config, SyncTransport(
        config.api_url,
        headers={**config.headers, "X-API-Key": config.api_key},
        timeout=config.request_timeout,
    )


def _async_control(
    api_key: str | None,
    api_url: str | None,
    gateway_url: str | None,
    request_timeout: float,
    headers: Mapping[str, str] | None,
) -> tuple[ConnectionConfig, AsyncTransport]:
    config = ConnectionConfig.resolve(
        api_key=api_key,
        api_url=api_url,
        gateway_url=gateway_url,
        request_timeout=request_timeout,
        headers=headers,
    )
    return config, AsyncTransport(
        config.api_url,
        headers={**config.headers, "X-API-Key": config.api_key},
        timeout=config.request_timeout,
    )


def _create_body(
    template: str,
    timeout: int,
    envs: Mapping[str, str] | None,
    metadata: Mapping[str, str] | None,
    network: NetworkConfig | None,
    auto_pause: bool,
    auto_pause_memory: bool,
    auto_resume: bool,
    secure: bool,
    client_id: str | None,
    build_id: str | None,
    volume_mounts: Sequence[VolumeMount],
) -> dict[str, object]:
    if not template.strip():
        raise ValueError("template must not be blank")
    resolved_network = network or NetworkConfig()
    body: dict[str, object] = {
        "templateID": template,
        "timeout": _checked_timeout(timeout),
        "autoPause": auto_pause,
        "autoResume": {"enabled": auto_resume},
        "secure": secure,
        "allow_internet_access": resolved_network.allow_internet_access,
        "network": resolved_network.to_create_wire(),
        "metadata": dict(metadata or {}),
        "envVars": dict(envs or {}),
        "volumeMounts": [item.to_wire() for item in volume_mounts],
    }
    if auto_pause:
        body["autoPauseMemory"] = auto_pause_memory
    if client_id:
        body["clientID"] = client_id
    if build_id:
        body["buildID"] = build_id
    return body


def _sandbox_payload(value: object) -> tuple[SandboxInfo, SandboxConnection]:
    payload = _mapping(value)
    sandbox = _mapping(payload.get("sandbox", payload))
    info = SandboxInfo.from_wire(sandbox)
    connection = payload.get("connection", sandbox.get("connection", sandbox))
    return info, SandboxConnection.from_wire(_mapping(connection), info.sandbox_id)


def _sandbox_page(value: object, next_token: str | None, total: str | None) -> Page[SandboxInfo]:
    return Page(
        tuple(SandboxInfo.from_wire(item) for item in _items(value)),
        next_token or None,
        _response_integer(total, "X-Total-Running") if total else None,
    )


def _snapshot_page(value: object, next_token: str | None) -> Page[SnapshotInfo]:
    return Page(tuple(SnapshotInfo.from_wire(item) for item in _items(value)), next_token or None)


def _list_params(
    metadata: str | None,
    states: Sequence[SandboxState | str],
    limit: int | None,
    next_token: str | None,
) -> dict[str, str | int]:
    params: dict[str, str | int] = {}
    if metadata:
        params["metadata"] = metadata
    if states:
        params["state"] = ",".join(
            item.value if isinstance(item, SandboxState) else item for item in states
        )
    if limit is not None:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        params["limit"] = limit
    if next_token:
        params["nextToken"] = next_token
    return params


def _snapshot_params(
    sandbox_id: str | None, name: str | None, limit: int | None, next_token: str | None
) -> dict[str, str | int]:
    params: dict[str, str | int] = {}
    for key, value in (("sandboxID", sandbox_id), ("name", name), ("nextToken", next_token)):
        if value:
            params[key] = value
    if limit is not None:
        params["limit"] = limit
    return params


def _log_params(
    cursor: int | None,
    limit: int,
    direction: LogsDirection | str | None,
    level: LogLevel | str | None,
    search: str | None,
) -> dict[str, str | int]:
    if not 0 <= limit <= 1000:
        raise ValueError("limit must be between 0 and 1000")
    if search is not None and len(search) > 256:
        raise ValueError("search must not exceed 256 characters")
    params: dict[str, str | int] = {"limit": limit}
    if cursor is not None:
        params["cursor"] = cursor
    if direction:
        params["direction"] = direction.value if isinstance(direction, LogsDirection) else direction
    if level:
        params["level"] = level.value if isinstance(level, LogLevel) else level
    if search:
        params["search"] = search
    return params


def _metric_params(start: int | datetime | None, end: int | datetime | None) -> dict[str, int]:
    params: dict[str, int] = {}
    if start is not None:
        params["start"] = int(start.timestamp()) if isinstance(start, datetime) else start
    if end is not None:
        params["end"] = int(end.timestamp()) if isinstance(end, datetime) else end
    return params


def _fork_body(timeout: int, count: int) -> dict[str, int]:
    if not 1 <= count <= 100:
        raise ValueError("count must be between 1 and 100")
    return {"timeout": _checked_timeout(timeout), "count": count}


def _fork_result(
    value: Mapping[str, Any],
    control: SyncTransport,
    request_timeout: float,
    gateway_url: str | None = None,
) -> SandboxForkResult:
    raw = value.get("sandbox")
    sandbox = None
    if isinstance(raw, Mapping):
        info, connection = _sandbox_payload(raw)
        sandbox = Sandbox(
            control,
            info,
            connection,
            request_timeout=request_timeout,
            gateway_url=gateway_url,
        )
    return SandboxForkResult(sandbox, _error_detail(value.get("error")))


def _async_fork_result(
    value: Mapping[str, Any],
    control: AsyncTransport,
    request_timeout: float,
    gateway_url: str | None = None,
) -> AsyncSandboxForkResult:
    raw = value.get("sandbox")
    sandbox = None
    if isinstance(raw, Mapping):
        info, connection = _sandbox_payload(raw)
        sandbox = AsyncSandbox(
            control,
            info,
            connection,
            request_timeout=request_timeout,
            gateway_url=gateway_url,
        )
    return AsyncSandboxForkResult(sandbox, _error_detail(value.get("error")))


def _error_detail(value: object) -> ErrorDetail | None:
    if not isinstance(value, Mapping):
        return None
    return ErrorDetail(str(value.get("error", "")), str(value.get("message", "")))


def _sandbox_ids(values: Sequence[str]) -> tuple[str, ...]:
    ids = tuple(dict.fromkeys(value for value in values if value))
    if not ids or len(ids) > 100:
        raise ValueError("sandbox_ids must contain between 1 and 100 unique IDs")
    return ids


def _items(value: object) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, list | tuple):
        raise ProtocolError("DevBox returned an invalid list response")
    return tuple(_mapping(item) for item in value)


def _mapping(value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ProtocolError("DevBox returned an invalid object response")
    return value


def _checked_timeout(timeout: int) -> int:
    if not 0 <= timeout <= 3600:
        raise ValueError("timeout must be between 0 and 3600 seconds")
    return timeout


def _response_integer(value: str, field: str) -> int:
    try:
        return int(value)
    except ValueError as error:
        raise ProtocolError(f"DevBox response header is not an integer: {field}") from error


def _id(value: str) -> str:
    if not value:
        raise ValueError("identifier must not be blank")
    return quote(value, safe="")


def _gateway_headers(connection: SandboxConnection) -> dict[str, str]:
    return {"X-Access-Token": connection.access_token, "E2B-Sandbox-Id": connection.sandbox_id}


def _gateway_url(connection: SandboxConnection, configured_url: str | None = None) -> str:
    if configured_url:
        return configured_url
    url = connection.gateway_url
    if not url:
        raise ProtocolError("sandbox response does not provide an EnvD endpoint")
    if url.removeprefix("https://").endswith(".sandbox.devbox.local"):
        raise ProtocolError("Manager returned a placeholder EnvD endpoint")
    return url


def _expires_soon(expires_at: datetime | None) -> bool:
    return bool(expires_at and expires_at <= datetime.now(timezone.utc) + timedelta(seconds=30))
