from __future__ import annotations

from collections.abc import Mapping
from types import TracebackType

import httpx

from ._transport import AsyncTransport, SyncTransport
from .config import ConnectionConfig
from .nodes import AsyncNodes, Nodes
from .sandbox import AsyncSandboxes, AsyncSnapshots, Sandboxes, Snapshots
from .templates import AsyncTemplates, Templates


class DevBox:
    """Reusable synchronous DevBox client."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        api_url: str | None = None,
        gateway_url: str | None = None,
        request_timeout: float = 30.0,
        headers: Mapping[str, str] | None = None,
        http_transport: httpx.BaseTransport | None = None,
    ) -> None:
        config = ConnectionConfig.resolve(
            api_key=api_key,
            api_url=api_url,
            gateway_url=gateway_url,
            request_timeout=request_timeout,
            headers=headers,
        )
        request_headers = {**config.headers, "X-API-Key": config.api_key}
        self._transport = SyncTransport(
            config.api_url,
            headers=request_headers,
            timeout=config.request_timeout,
            transport=http_transport,
        )
        self.sandboxes = Sandboxes(
            self._transport,
            config.request_timeout,
            gateway_url=config.gateway_url,
        )
        self.snapshots = Snapshots(self._transport)
        self.templates = Templates(self._transport)
        self.nodes = Nodes(self._transport)

    def close(self) -> None:
        self._transport.close()

    def __enter__(self) -> DevBox:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()


class AsyncDevBox:
    """Reusable asynchronous DevBox client."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        api_url: str | None = None,
        gateway_url: str | None = None,
        request_timeout: float = 30.0,
        headers: Mapping[str, str] | None = None,
        http_transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        config = ConnectionConfig.resolve(
            api_key=api_key,
            api_url=api_url,
            gateway_url=gateway_url,
            request_timeout=request_timeout,
            headers=headers,
        )
        request_headers = {**config.headers, "X-API-Key": config.api_key}
        self._transport = AsyncTransport(
            config.api_url,
            headers=request_headers,
            timeout=config.request_timeout,
            transport=http_transport,
        )
        self.sandboxes = AsyncSandboxes(
            self._transport,
            config.request_timeout,
            gateway_url=config.gateway_url,
        )
        self.snapshots = AsyncSnapshots(self._transport)
        self.templates = AsyncTemplates(self._transport)
        self.nodes = AsyncNodes(self._transport)

    async def close(self) -> None:
        await self._transport.close()

    async def __aenter__(self) -> AsyncDevBox:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.close()
