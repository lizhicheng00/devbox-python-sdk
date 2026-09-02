from __future__ import annotations

import base64
from collections.abc import Mapping
from typing import Any

import pytest

from devbox.filesystem import Filesystem


class FilesystemTransport:
    def __init__(self) -> None:
        self.body: Mapping[str, Any] = {}

    def request(self, method: str, path: str, *, json_body: object | None = None) -> object:
        assert isinstance(json_body, Mapping)
        self.body = json_body
        return {
            "name": "data.bin",
            "path": "/tmp/data.bin",
            "type": "file",
            "size": 3,
        }

    def request_bytes(
        self, method: str, path: str, *, params: Mapping[str, object] | None = None
    ) -> bytes:
        assert params == {"path": "/tmp/data.bin"}
        return b"\x00\x01\x02"


def test_files_are_transferred_as_binary() -> None:
    transport = FilesystemTransport()
    files = Filesystem(lambda: transport)  # type: ignore[arg-type]

    info = files.write("/tmp/data.bin", b"\x00\x01\x02")

    assert info.size == 3
    assert base64.b64decode(str(transport.body["content"])) == b"\x00\x01\x02"
    assert files.read_bytes("/tmp/data.bin") == b"\x00\x01\x02"


def test_sandbox_path_must_be_absolute() -> None:
    transport = FilesystemTransport()
    files = Filesystem(lambda: transport)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="absolute"):
        files.read("relative.txt")
