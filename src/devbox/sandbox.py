from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from types import TracebackType
from typing import Any
from urllib.parse import quote
from uuid import uuid4

import httpx

from ._transport import AsyncTransport, SyncTransport
from .commands import AsyncCommands, Commands
from .config import ConnectionConfig
from .errors import ProtocolError
from .filesystem import AsyncFilesystem, Filesystem
from .git import AsyncGit, Git
from .models import (
    NetworkConfig,
    Page,
    SandboxConnection,
    SandboxInfo,
    SandboxMetrics,
    SandboxState,
    SnapshotInfo,
)
from .pty import AsyncPty, Pty


class Sandboxes:
    def __init__(self, transport: SyncTransport, request_timeout: float = 30.0) -> None:
        self._transport = transport
        self._request_timeout = request_timeout

    def create(
        self,
        template: str = "base",
        *,
        timeout: int = 300,
        envs: Mapping[str, str] | None = None,
        metadata: Mapping[str, str] | None = None,
        network: NetworkConfig | None = None,
        webhook_url: str | None = None,
        idempotency_key: str | None = None,
    ) -> Sandbox:
        body = _create_body(template, timeout, envs, metadata, network, webhook_url)
        headers = {"Idempotency-Key": idempotency_key or str(uuid4())}
        payload = self._transport.request("POST", "/sandboxes", json_body=body, headers=headers)
        info, connection = _sandbox_payload(payload)
        return Sandbox(self._transport, info, connection, request_timeout=self._request_timeout)

    def connect(self, sandbox_id: str, *, timeout: int | None = None) -> Sandbox:
        payload = self._transport.request(
            "POST", f"/sandboxes/{_id(sandbox_id)}/connect", json_body=_timeout_body(timeout)
        )
        info, connection = _sandbox_payload(payload)
        return Sandbox(self._transport, info, connection, request_timeout=self._request_timeout)

    def get(self, sandbox_id: str) -> SandboxInfo:
        payload = self._transport.request("GET", f"/sandboxes/{_id(sandbox_id)}")
        return SandboxInfo.from_wire(_mapping(payload))

    def list(
        self,
        *,
        states: Sequence[SandboxState | str] | None = None,
        limit: int | None = None,
        next_token: str | None = None,
    ) -> Page[SandboxInfo]:
        params: dict[str, str | int] = {}
        if states:
            params["state"] = ",".join(
                state.value if isinstance(state, SandboxState) else state for state in states
            )
        if limit is not None:
            params["limit"] = limit
        if next_token:
            params["nextToken"] = next_token
        return _sandbox_page(self._transport.request("GET", "/sandboxes", params=params))


class AsyncSandboxes:
    def __init__(self, transport: AsyncTransport, request_timeout: float = 30.0) -> None:
        self._transport = transport
        self._request_timeout = request_timeout

    async def create(
        self,
        template: str = "base",
        *,
        timeout: int = 300,
        envs: Mapping[str, str] | None = None,
        metadata: Mapping[str, str] | None = None,
        network: NetworkConfig | None = None,
        webhook_url: str | None = None,
        idempotency_key: str | None = None,
    ) -> AsyncSandbox:
        body = _create_body(template, timeout, envs, metadata, network, webhook_url)
        headers = {"Idempotency-Key": idempotency_key or str(uuid4())}
        payload = await self._transport.request(
            "POST", "/sandboxes", json_body=body, headers=headers
        )
        info, connection = _sandbox_payload(payload)
        return AsyncSandbox(
            self._transport, info, connection, request_timeout=self._request_timeout
        )

    async def connect(self, sandbox_id: str, *, timeout: int | None = None) -> AsyncSandbox:
        payload = await self._transport.request(
            "POST", f"/sandboxes/{_id(sandbox_id)}/connect", json_body=_timeout_body(timeout)
        )
        info, connection = _sandbox_payload(payload)
        return AsyncSandbox(
            self._transport, info, connection, request_timeout=self._request_timeout
        )

    async def get(self, sandbox_id: str) -> SandboxInfo:
        payload = await self._transport.request("GET", f"/sandboxes/{_id(sandbox_id)}")
        return SandboxInfo.from_wire(_mapping(payload))

    async def list(
        self,
        *,
        states: Sequence[SandboxState | str] | None = None,
        limit: int | None = None,
        next_token: str | None = None,
    ) -> Page[SandboxInfo]:
        params: dict[str, str | int] = {}
        if states:
            params["state"] = ",".join(
                state.value if isinstance(state, SandboxState) else state for state in states
            )
        if limit is not None:
            params["limit"] = limit
        if next_token:
            params["nextToken"] = next_token
        return _sandbox_page(await self._transport.request("GET", "/sandboxes", params=params))


class Snapshots:
    def __init__(self, transport: SyncTransport) -> None:
        self._transport = transport

    def list(
        self, *, limit: int | None = None, next_token: str | None = None
    ) -> Page[SnapshotInfo]:
        params: dict[str, str | int] = {}
        if limit is not None:
            params["limit"] = limit
        if next_token:
            params["nextToken"] = next_token
        return _snapshot_page(self._transport.request("GET", "/snapshots", params=params))


class AsyncSnapshots:
    def __init__(self, transport: AsyncTransport) -> None:
        self._transport = transport

    async def list(
        self, *, limit: int | None = None, next_token: str | None = None
    ) -> Page[SnapshotInfo]:
        params: dict[str, str | int] = {}
        if limit is not None:
            params["limit"] = limit
        if next_token:
            params["nextToken"] = next_token
        payload = await self._transport.request("GET", "/snapshots", params=params)
        return _snapshot_page(payload)


class Sandbox:
    """A connected synchronous sandbox."""

    def __init__(
        self,
        control: SyncTransport,
        info: SandboxInfo,
        connection: SandboxConnection,
        *,
        owns_control: bool = False,
        request_timeout: float = 30.0,
    ) -> None:
        self._control = control
        self._info = info
        self._connection = connection
        self._owns_control = owns_control
        self._request_timeout = request_timeout
        self._gateway: SyncTransport | None = None
        self.commands = Commands(self._gateway_transport)
        self.files = Filesystem(self._gateway_transport)
        self.pty = Pty(self.commands, self._gateway_transport)
        self.git = Git(self.commands)

    @classmethod
    def create(
        cls,
        template: str = "base",
        *,
        timeout: int = 300,
        envs: Mapping[str, str] | None = None,
        metadata: Mapping[str, str] | None = None,
        network: NetworkConfig | None = None,
        webhook_url: str | None = None,
        api_key: str | None = None,
        api_url: str | None = None,
        request_timeout: float = 30.0,
        idempotency_key: str | None = None,
        http_transport: httpx.BaseTransport | None = None,
    ) -> Sandbox:
        config, transport = _sync_control(api_key, api_url, request_timeout, http_transport)
        try:
            sandbox = Sandboxes(transport, config.request_timeout).create(
                template,
                timeout=timeout,
                envs=envs,
                metadata=metadata,
                network=network,
                webhook_url=webhook_url,
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
        timeout: int | None = None,
        api_key: str | None = None,
        api_url: str | None = None,
        request_timeout: float = 30.0,
        http_transport: httpx.BaseTransport | None = None,
    ) -> Sandbox:
        config, transport = _sync_control(api_key, api_url, request_timeout, http_transport)
        try:
            sandbox = Sandboxes(transport, config.request_timeout).connect(
                sandbox_id, timeout=timeout
            )
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

    def pause(self) -> bool:
        result = self._control.request("POST", f"/sandboxes/{_id(self.sandbox_id)}/pause")
        self._close_gateway()
        return _changed(result)

    def resume(self) -> bool:
        result = self._control.request("POST", f"/sandboxes/{_id(self.sandbox_id)}/resume")
        self._reconnect()
        return _changed(result)

    def set_timeout(self, timeout: int) -> None:
        _validate_timeout(timeout)
        self._control.request(
            "POST", f"/sandboxes/{_id(self.sandbox_id)}/timeout", json_body={"timeout": timeout}
        )

    def refresh(self) -> None:
        self._control.request("POST", f"/sandboxes/{_id(self.sandbox_id)}/refresh")

    def kill(self) -> bool:
        result = self._control.request("DELETE", f"/sandboxes/{_id(self.sandbox_id)}")
        self._close_gateway()
        return _changed(result)

    def snapshot(self, *, idempotency_key: str | None = None) -> SnapshotInfo:
        payload = self._control.request(
            "POST",
            f"/sandboxes/{_id(self.sandbox_id)}/snapshot",
            headers={"Idempotency-Key": idempotency_key or str(uuid4())},
        )
        return SnapshotInfo.from_wire(_mapping(payload))

    def fork(self, *, timeout: int | None = None, idempotency_key: str | None = None) -> Sandbox:
        payload = self._control.request(
            "POST",
            f"/sandboxes/{_id(self.sandbox_id)}/fork",
            json_body=_timeout_body(timeout),
            headers={"Idempotency-Key": idempotency_key or str(uuid4())},
        )
        info, connection = _sandbox_payload(payload)
        return Sandbox(
            self._control,
            info,
            connection,
            request_timeout=self._request_timeout,
        )

    def get_logs(self) -> tuple[str, ...]:
        payload = self._control.request("GET", f"/sandboxes/{_id(self.sandbox_id)}/logs")
        if isinstance(payload, list):
            return tuple(str(line) for line in payload)
        body = _mapping(payload)
        values = body.get("logs", body.get("items", []))
        return tuple(str(line) for line in values) if isinstance(values, list) else ()

    def get_metrics(
        self, *, start: datetime | None = None, end: datetime | None = None
    ) -> tuple[SandboxMetrics, ...]:
        payload = self._control.request(
            "GET", f"/sandboxes/{_id(self.sandbox_id)}/metrics", params=_time_range(start, end)
        )
        return tuple(SandboxMetrics.from_wire(item) for item in _items(payload, "metrics"))

    def update_network(self, network: NetworkConfig) -> None:
        self._control.request(
            "PUT",
            f"/sandboxes/{_id(self.sandbox_id)}/network",
            json_body=network.to_wire(),
        )

    def close(self) -> None:
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
        self.close()

    def _gateway_transport(self) -> SyncTransport:
        if _expires_soon(self._connection.expires_at):
            self._reconnect()
        if self._gateway is None:
            self._gateway = SyncTransport(
                self._connection.gateway_url,
                headers=_gateway_headers(self._connection),
                timeout=self._request_timeout,
            )
        return self._gateway

    def _reconnect(self) -> None:
        payload = self._control.request("POST", f"/sandboxes/{_id(self.sandbox_id)}/connect")
        info, connection = _sandbox_payload(payload)
        self._info = info
        self._connection = connection
        self._close_gateway()

    def _close_gateway(self) -> None:
        if self._gateway is not None:
            self._gateway.close()
            self._gateway = None


class AsyncSandbox:
    """A connected asynchronous sandbox."""

    def __init__(
        self,
        control: AsyncTransport,
        info: SandboxInfo,
        connection: SandboxConnection,
        *,
        owns_control: bool = False,
        request_timeout: float = 30.0,
    ) -> None:
        self._control = control
        self._info = info
        self._connection = connection
        self._owns_control = owns_control
        self._request_timeout = request_timeout
        self._gateway: AsyncTransport | None = None
        self.commands = AsyncCommands(self._gateway_transport)
        self.files = AsyncFilesystem(self._gateway_transport)
        self.pty = AsyncPty(self.commands, self._gateway_transport)
        self.git = AsyncGit(self.commands)

    @classmethod
    async def create(
        cls,
        template: str = "base",
        *,
        timeout: int = 300,
        envs: Mapping[str, str] | None = None,
        metadata: Mapping[str, str] | None = None,
        network: NetworkConfig | None = None,
        webhook_url: str | None = None,
        api_key: str | None = None,
        api_url: str | None = None,
        request_timeout: float = 30.0,
        idempotency_key: str | None = None,
        http_transport: httpx.AsyncBaseTransport | None = None,
    ) -> AsyncSandbox:
        config, transport = _async_control(api_key, api_url, request_timeout, http_transport)
        try:
            sandbox = await AsyncSandboxes(transport, config.request_timeout).create(
                template,
                timeout=timeout,
                envs=envs,
                metadata=metadata,
                network=network,
                webhook_url=webhook_url,
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
        timeout: int | None = None,
        api_key: str | None = None,
        api_url: str | None = None,
        request_timeout: float = 30.0,
        http_transport: httpx.AsyncBaseTransport | None = None,
    ) -> AsyncSandbox:
        config, transport = _async_control(api_key, api_url, request_timeout, http_transport)
        try:
            sandbox = await AsyncSandboxes(transport, config.request_timeout).connect(
                sandbox_id, timeout=timeout
            )
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

    async def pause(self) -> bool:
        result = await self._control.request("POST", f"/sandboxes/{_id(self.sandbox_id)}/pause")
        await self._close_gateway()
        return _changed(result)

    async def resume(self) -> bool:
        result = await self._control.request("POST", f"/sandboxes/{_id(self.sandbox_id)}/resume")
        await self._reconnect()
        return _changed(result)

    async def set_timeout(self, timeout: int) -> None:
        _validate_timeout(timeout)
        await self._control.request(
            "POST", f"/sandboxes/{_id(self.sandbox_id)}/timeout", json_body={"timeout": timeout}
        )

    async def refresh(self) -> None:
        await self._control.request("POST", f"/sandboxes/{_id(self.sandbox_id)}/refresh")

    async def kill(self) -> bool:
        result = await self._control.request("DELETE", f"/sandboxes/{_id(self.sandbox_id)}")
        await self._close_gateway()
        return _changed(result)

    async def snapshot(self, *, idempotency_key: str | None = None) -> SnapshotInfo:
        payload = await self._control.request(
            "POST",
            f"/sandboxes/{_id(self.sandbox_id)}/snapshot",
            headers={"Idempotency-Key": idempotency_key or str(uuid4())},
        )
        return SnapshotInfo.from_wire(_mapping(payload))

    async def fork(
        self, *, timeout: int | None = None, idempotency_key: str | None = None
    ) -> AsyncSandbox:
        payload = await self._control.request(
            "POST",
            f"/sandboxes/{_id(self.sandbox_id)}/fork",
            json_body=_timeout_body(timeout),
            headers={"Idempotency-Key": idempotency_key or str(uuid4())},
        )
        info, connection = _sandbox_payload(payload)
        return AsyncSandbox(
            self._control,
            info,
            connection,
            request_timeout=self._request_timeout,
        )

    async def get_logs(self) -> tuple[str, ...]:
        payload = await self._control.request("GET", f"/sandboxes/{_id(self.sandbox_id)}/logs")
        if isinstance(payload, list):
            return tuple(str(line) for line in payload)
        body = _mapping(payload)
        values = body.get("logs", body.get("items", []))
        return tuple(str(line) for line in values) if isinstance(values, list) else ()

    async def get_metrics(
        self, *, start: datetime | None = None, end: datetime | None = None
    ) -> tuple[SandboxMetrics, ...]:
        payload = await self._control.request(
            "GET", f"/sandboxes/{_id(self.sandbox_id)}/metrics", params=_time_range(start, end)
        )
        return tuple(SandboxMetrics.from_wire(item) for item in _items(payload, "metrics"))

    async def update_network(self, network: NetworkConfig) -> None:
        await self._control.request(
            "PUT",
            f"/sandboxes/{_id(self.sandbox_id)}/network",
            json_body=network.to_wire(),
        )

    async def close(self) -> None:
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
        await self.close()

    async def _gateway_transport(self) -> AsyncTransport:
        if _expires_soon(self._connection.expires_at):
            await self._reconnect()
        if self._gateway is None:
            self._gateway = AsyncTransport(
                self._connection.gateway_url,
                headers=_gateway_headers(self._connection),
                timeout=self._request_timeout,
            )
        return self._gateway

    async def _reconnect(self) -> None:
        payload = await self._control.request("POST", f"/sandboxes/{_id(self.sandbox_id)}/connect")
        info, connection = _sandbox_payload(payload)
        self._info = info
        self._connection = connection
        await self._close_gateway()

    async def _close_gateway(self) -> None:
        if self._gateway is not None:
            await self._gateway.close()
            self._gateway = None


def _sync_control(
    api_key: str | None,
    api_url: str | None,
    request_timeout: float,
    http_transport: httpx.BaseTransport | None,
) -> tuple[ConnectionConfig, SyncTransport]:
    config = ConnectionConfig.resolve(
        api_key=api_key, api_url=api_url, request_timeout=request_timeout
    )
    transport = SyncTransport(
        config.api_url,
        headers={**config.headers, "X-API-Key": config.api_key},
        timeout=config.request_timeout,
        transport=http_transport,
    )
    return config, transport


def _async_control(
    api_key: str | None,
    api_url: str | None,
    request_timeout: float,
    http_transport: httpx.AsyncBaseTransport | None,
) -> tuple[ConnectionConfig, AsyncTransport]:
    config = ConnectionConfig.resolve(
        api_key=api_key, api_url=api_url, request_timeout=request_timeout
    )
    transport = AsyncTransport(
        config.api_url,
        headers={**config.headers, "X-API-Key": config.api_key},
        timeout=config.request_timeout,
        transport=http_transport,
    )
    return config, transport


def _create_body(
    template: str,
    timeout: int,
    envs: Mapping[str, str] | None,
    metadata: Mapping[str, str] | None,
    network: NetworkConfig | None,
    webhook_url: str | None,
) -> dict[str, object]:
    _validate_timeout(timeout)
    if not template.strip():
        raise ValueError("template must not be blank")
    body: dict[str, object] = {
        "template": template,
        "timeout": timeout,
        "envs": dict(envs or {}),
        "metadata": dict(metadata or {}),
        "network": (network or NetworkConfig()).to_wire(),
    }
    if webhook_url:
        body["webhookUrl"] = webhook_url
    return body


def _sandbox_payload(value: object) -> tuple[SandboxInfo, SandboxConnection]:
    payload = _mapping(value)
    raw_sandbox = payload.get("sandbox", payload)
    sandbox = _mapping(raw_sandbox)
    info = SandboxInfo.from_wire(sandbox)
    raw_connection = payload.get("connection", sandbox.get("connection"))
    if not isinstance(raw_connection, Mapping):
        raise ProtocolError("sandbox response does not contain connection details")
    return info, SandboxConnection.from_wire(raw_connection, info.sandbox_id)


def _sandbox_page(value: object) -> Page[SandboxInfo]:
    if isinstance(value, list):
        return Page(tuple(SandboxInfo.from_wire(_mapping(item)) for item in value))
    payload = _mapping(value)
    return Page(
        tuple(SandboxInfo.from_wire(item) for item in _items(payload, "sandboxes")),
        str(payload["nextToken"]) if payload.get("nextToken") else None,
    )


def _snapshot_page(value: object) -> Page[SnapshotInfo]:
    if isinstance(value, list):
        return Page(tuple(SnapshotInfo.from_wire(_mapping(item)) for item in value))
    payload = _mapping(value)
    return Page(
        tuple(SnapshotInfo.from_wire(item) for item in _items(payload, "snapshots")),
        str(payload["nextToken"]) if payload.get("nextToken") else None,
    )


def _items(value: object, key: str) -> tuple[Mapping[str, Any], ...]:
    if isinstance(value, list):
        source = value
    else:
        payload = _mapping(value)
        source = payload.get(key, payload.get("items", []))
    if not isinstance(source, list):
        raise ProtocolError("DevBox returned an invalid list response")
    return tuple(_mapping(item) for item in source)


def _mapping(value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ProtocolError("DevBox returned an invalid object response")
    return value


def _timeout_body(timeout: int | None) -> dict[str, int]:
    if timeout is None:
        return {}
    _validate_timeout(timeout)
    return {"timeout": timeout}


def _validate_timeout(timeout: int) -> None:
    if timeout < 1 or timeout > 3600:
        raise ValueError("timeout must be between 1 and 3600 seconds")


def _id(value: str) -> str:
    if not value:
        raise ValueError("sandbox_id must not be blank")
    return quote(value, safe="")


def _changed(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, bool):
        return value
    if isinstance(value, Mapping):
        return bool(value.get("changed", value.get("success", True)))
    return True


def _gateway_headers(connection: SandboxConnection) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {connection.access_token}",
        "E2B-Sandbox-Id": connection.sandbox_id,
    }


def _expires_soon(expires_at: datetime | None) -> bool:
    if expires_at is None:
        return False
    return expires_at <= datetime.now(timezone.utc) + timedelta(seconds=30)


def _time_range(start: datetime | None, end: datetime | None) -> dict[str, str]:
    params: dict[str, str] = {}
    if start:
        params["start"] = start.astimezone(timezone.utc).isoformat()
    if end:
        params["end"] = end.astimezone(timezone.utc).isoformat()
    return params
