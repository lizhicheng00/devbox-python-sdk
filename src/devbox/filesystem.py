from __future__ import annotations

import base64
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

from ._transport import AsyncTransport, SyncTransport
from .errors import ProtocolError
from .models import FileInfo

SyncTransportProvider = Callable[[], SyncTransport]
AsyncTransportProvider = Callable[[], Awaitable[AsyncTransport]]


class Filesystem:
    def __init__(self, transport: SyncTransportProvider) -> None:
        self._transport = transport

    def read_bytes(self, path: str) -> bytes:
        return self._transport().request_bytes(
            "GET", "/envd/filesystem/download", params={"path": _path(path)}
        )

    def read(self, path: str, *, encoding: str = "utf-8") -> str:
        return self.read_bytes(path).decode(encoding)

    def write(
        self,
        path: str,
        data: str | bytes,
        *,
        encoding: str = "utf-8",
        mode: int | None = None,
    ) -> FileInfo:
        content = data.encode(encoding) if isinstance(data, str) else data
        payload = self._transport().request(
            "POST",
            "/envd/filesystem/upload",
            json_body=_write_body(path, content, mode),
        )
        return FileInfo.from_wire(_mapping(payload))

    def write_batch(
        self, files: Mapping[str, str | bytes], *, encoding: str = "utf-8"
    ) -> tuple[FileInfo, ...]:
        entries = [
            _write_body(path, data.encode(encoding) if isinstance(data, str) else data, None)
            for path, data in files.items()
        ]
        payload = self._transport().request(
            "POST", "/envd/filesystem/upload", json_body={"files": entries}
        )
        return tuple(FileInfo.from_wire(item) for item in _items(payload, "files"))

    def list(self, path: str) -> tuple[FileInfo, ...]:
        payload = self._transport().request(
            "POST", "/envd/filesystem/list-dir", json_body={"path": _path(path)}
        )
        return tuple(FileInfo.from_wire(item) for item in _items(payload, "entries"))

    def stat(self, path: str) -> FileInfo:
        payload = self._transport().request(
            "POST", "/envd/filesystem/stat", json_body={"path": _path(path)}
        )
        return FileInfo.from_wire(_mapping(payload))

    def make_dir(self, path: str, *, parents: bool = True, mode: int | None = None) -> None:
        self._transport().request(
            "POST",
            "/envd/filesystem/make-dir",
            json_body={"path": _path(path), "parents": parents, "mode": mode},
        )

    def move(self, source: str, destination: str) -> None:
        self._transport().request(
            "POST",
            "/envd/filesystem/move",
            json_body={"source": _path(source), "destination": _path(destination)},
        )

    def remove(self, path: str, *, recursive: bool = False) -> None:
        self._transport().request(
            "POST",
            "/envd/filesystem/remove",
            json_body={"path": _path(path), "recursive": recursive},
        )

    def upload(self, local_path: str | Path, remote_path: str) -> FileInfo:
        return self.write(remote_path, Path(local_path).read_bytes())

    def download(self, remote_path: str, local_path: str | Path) -> Path:
        destination = Path(local_path)
        destination.write_bytes(self.read_bytes(remote_path))
        return destination

    def watch(self, path: str) -> Iterator[Mapping[str, Any]]:
        yield from self._transport().iter_events(
            "POST", "/envd/filesystem/watch-dir", json_body={"path": _path(path)}
        )


class AsyncFilesystem:
    def __init__(self, transport: AsyncTransportProvider) -> None:
        self._transport = transport

    async def read_bytes(self, path: str) -> bytes:
        transport = await self._transport()
        return await transport.request_bytes(
            "GET", "/envd/filesystem/download", params={"path": _path(path)}
        )

    async def read(self, path: str, *, encoding: str = "utf-8") -> str:
        return (await self.read_bytes(path)).decode(encoding)

    async def write(
        self,
        path: str,
        data: str | bytes,
        *,
        encoding: str = "utf-8",
        mode: int | None = None,
    ) -> FileInfo:
        content = data.encode(encoding) if isinstance(data, str) else data
        transport = await self._transport()
        payload = await transport.request(
            "POST", "/envd/filesystem/upload", json_body=_write_body(path, content, mode)
        )
        return FileInfo.from_wire(_mapping(payload))

    async def write_batch(
        self, files: Mapping[str, str | bytes], *, encoding: str = "utf-8"
    ) -> tuple[FileInfo, ...]:
        entries = [
            _write_body(path, data.encode(encoding) if isinstance(data, str) else data, None)
            for path, data in files.items()
        ]
        transport = await self._transport()
        payload = await transport.request(
            "POST", "/envd/filesystem/upload", json_body={"files": entries}
        )
        return tuple(FileInfo.from_wire(item) for item in _items(payload, "files"))

    async def list(self, path: str) -> tuple[FileInfo, ...]:
        transport = await self._transport()
        payload = await transport.request(
            "POST", "/envd/filesystem/list-dir", json_body={"path": _path(path)}
        )
        return tuple(FileInfo.from_wire(item) for item in _items(payload, "entries"))

    async def stat(self, path: str) -> FileInfo:
        transport = await self._transport()
        payload = await transport.request(
            "POST", "/envd/filesystem/stat", json_body={"path": _path(path)}
        )
        return FileInfo.from_wire(_mapping(payload))

    async def make_dir(self, path: str, *, parents: bool = True, mode: int | None = None) -> None:
        transport = await self._transport()
        await transport.request(
            "POST",
            "/envd/filesystem/make-dir",
            json_body={"path": _path(path), "parents": parents, "mode": mode},
        )

    async def move(self, source: str, destination: str) -> None:
        transport = await self._transport()
        await transport.request(
            "POST",
            "/envd/filesystem/move",
            json_body={"source": _path(source), "destination": _path(destination)},
        )

    async def remove(self, path: str, *, recursive: bool = False) -> None:
        transport = await self._transport()
        await transport.request(
            "POST",
            "/envd/filesystem/remove",
            json_body={"path": _path(path), "recursive": recursive},
        )

    async def upload(self, local_path: str | Path, remote_path: str) -> FileInfo:
        return await self.write(remote_path, Path(local_path).read_bytes())

    async def download(self, remote_path: str, local_path: str | Path) -> Path:
        destination = Path(local_path)
        destination.write_bytes(await self.read_bytes(remote_path))
        return destination

    async def watch(self, path: str) -> AsyncIterator[Mapping[str, Any]]:
        transport = await self._transport()
        async for event in transport.iter_events(
            "POST", "/envd/filesystem/watch-dir", json_body={"path": _path(path)}
        ):
            yield event


def _write_body(path: str, content: bytes, mode: int | None) -> dict[str, object]:
    return {
        "path": _path(path),
        "content": base64.b64encode(content).decode("ascii"),
        "encoding": "base64",
        "mode": mode,
    }


def _path(value: str) -> str:
    if not value or not value.startswith("/"):
        raise ValueError("sandbox paths must be absolute")
    return value


def _mapping(value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ProtocolError("filesystem response is invalid")
    return value


def _items(value: object, key: str) -> Sequence[Mapping[str, Any]]:
    if isinstance(value, list):
        source = value
    elif isinstance(value, Mapping):
        source = value.get(key, value.get("items", []))
    else:
        source = []
    if not isinstance(source, list):
        raise ProtocolError("filesystem response is invalid")
    return tuple(item for item in source if isinstance(item, Mapping))
