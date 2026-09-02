from __future__ import annotations

from urllib.parse import quote

from ._transport import AsyncTransport, SyncTransport
from .errors import ProtocolError
from .models import NodeInfo, NodeStatus


class Nodes:
    def __init__(self, transport: SyncTransport) -> None:
        self._transport = transport

    def list(self) -> tuple[NodeInfo, ...]:
        payload = _object(self._transport.request("GET", "/nodes"))
        return tuple(NodeInfo.from_wire(item) for item in _objects(payload.get("nodes")))

    def get(self, node_id: str) -> NodeInfo:
        return NodeInfo.from_wire(_object(self._transport.request("GET", f"/nodes/{_id(node_id)}")))

    def update_status(self, node_id: str, status: NodeStatus | str) -> NodeInfo:
        value = status.value if isinstance(status, NodeStatus) else NodeStatus(status).value
        payload = self._transport.request(
            "POST", f"/nodes/{_id(node_id)}", json_body={"status": value}
        )
        return NodeInfo.from_wire(_object(payload))


class AsyncNodes:
    def __init__(self, transport: AsyncTransport) -> None:
        self._transport = transport

    async def list(self) -> tuple[NodeInfo, ...]:
        payload = _object(await self._transport.request("GET", "/nodes"))
        return tuple(NodeInfo.from_wire(item) for item in _objects(payload.get("nodes")))

    async def get(self, node_id: str) -> NodeInfo:
        return NodeInfo.from_wire(
            _object(await self._transport.request("GET", f"/nodes/{_id(node_id)}"))
        )

    async def update_status(self, node_id: str, status: NodeStatus | str) -> NodeInfo:
        value = status.value if isinstance(status, NodeStatus) else NodeStatus(status).value
        payload = await self._transport.request(
            "POST", f"/nodes/{_id(node_id)}", json_body={"status": value}
        )
        return NodeInfo.from_wire(_object(payload))


def _id(value: str) -> str:
    if not value:
        raise ValueError("node_id must not be blank")
    return quote(value, safe="")


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ProtocolError("node response is invalid")
    return value


def _objects(value: object) -> tuple[dict[str, object], ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, dict))
