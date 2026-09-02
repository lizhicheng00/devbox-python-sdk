from __future__ import annotations

import base64
from collections.abc import AsyncIterator, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any
from urllib.parse import quote
from uuid import uuid4

from ._transport import AsyncTransport, SyncTransport
from .errors import ProtocolError
from .models import Page, TemplateBuildInfo, TemplateInfo


@dataclass(frozen=True, slots=True)
class TemplateFile:
    destination: str
    content: bytes = field(repr=False)
    mode: int | None = None

    def to_wire(self) -> dict[str, object]:
        return {
            "destination": self.destination,
            "content": base64.b64encode(self.content).decode("ascii"),
            "encoding": "base64",
            "mode": self.mode,
        }


@dataclass(frozen=True, slots=True)
class Template:
    image: str
    envs: Mapping[str, str] = field(default_factory=dict)
    files: tuple[TemplateFile, ...] = ()
    commands: tuple[str, ...] = ()
    start_command: str | None = None

    def __post_init__(self) -> None:
        if not self.image.strip():
            raise ValueError("template image must not be blank")

    @classmethod
    def from_image(cls, image: str) -> Template:
        return cls(image=image)

    def set_env(self, **envs: str) -> Template:
        return replace(self, envs={**self.envs, **envs})

    def copy(
        self,
        source: str | Path,
        destination: str,
        *,
        mode: int | None = None,
    ) -> Template:
        if not destination.startswith("/"):
            raise ValueError("template destination must be absolute")
        template_file = TemplateFile(destination, Path(source).read_bytes(), mode)
        return replace(self, files=(*self.files, template_file))

    def add_file(
        self,
        content: str | bytes,
        destination: str,
        *,
        encoding: str = "utf-8",
        mode: int | None = None,
    ) -> Template:
        if not destination.startswith("/"):
            raise ValueError("template destination must be absolute")
        raw = content.encode(encoding) if isinstance(content, str) else content
        return replace(self, files=(*self.files, TemplateFile(destination, raw, mode)))

    def run(self, *commands: str) -> Template:
        if not commands or any(not command.strip() for command in commands):
            raise ValueError("template command must not be blank")
        return replace(self, commands=(*self.commands, *commands))

    def set_start_command(self, command: str) -> Template:
        if not command.strip():
            raise ValueError("template start command must not be blank")
        return replace(self, start_command=command)

    def to_wire(self) -> dict[str, object]:
        return {
            "image": self.image,
            "envs": dict(self.envs),
            "files": [item.to_wire() for item in self.files],
            "commands": list(self.commands),
            "startCommand": self.start_command,
        }


class Templates:
    def __init__(self, transport: SyncTransport) -> None:
        self._transport = transport

    def create(
        self,
        definition: Template,
        *,
        alias: str | None = None,
        idempotency_key: str | None = None,
    ) -> TemplateInfo:
        body: dict[str, object] = {"definition": definition.to_wire()}
        if alias:
            body["alias"] = alias
        payload = self._transport.request(
            "POST",
            "/templates",
            json_body=body,
            headers={"Idempotency-Key": idempotency_key or str(uuid4())},
        )
        return TemplateInfo.from_wire(_mapping(payload))

    def list(
        self, *, limit: int | None = None, next_token: str | None = None
    ) -> Page[TemplateInfo]:
        params: dict[str, str | int] = {}
        if limit is not None:
            params["limit"] = limit
        if next_token:
            params["nextToken"] = next_token
        return _page(self._transport.request("GET", "/templates", params=params))

    def get(self, template_id: str) -> TemplateInfo:
        payload = self._transport.request("GET", f"/templates/{_id(template_id)}")
        return TemplateInfo.from_wire(_mapping(payload))

    def get_by_alias(self, alias: str) -> TemplateInfo:
        payload = self._transport.request("GET", f"/templates/alias/{_id(alias)}")
        return TemplateInfo.from_wire(_mapping(payload))

    def update(self, template_id: str, *, alias: str | None) -> TemplateInfo:
        payload = self._transport.request(
            "PATCH", f"/templates/{_id(template_id)}", json_body={"alias": alias}
        )
        return TemplateInfo.from_wire(_mapping(payload))

    def delete(self, template_id: str) -> None:
        self._transport.request("DELETE", f"/templates/{_id(template_id)}")

    def build(self, template_id: str, *, idempotency_key: str | None = None) -> TemplateBuildInfo:
        payload = self._transport.request(
            "POST",
            f"/templates/{_id(template_id)}/build",
            headers={"Idempotency-Key": idempotency_key or str(uuid4())},
        )
        return TemplateBuildInfo.from_wire(_mapping(payload))

    def rebuild(self, template_id: str, *, idempotency_key: str | None = None) -> TemplateBuildInfo:
        payload = self._transport.request(
            "POST",
            f"/templates/{_id(template_id)}/rebuild",
            headers={"Idempotency-Key": idempotency_key or str(uuid4())},
        )
        return TemplateBuildInfo.from_wire(_mapping(payload))

    def get_build(self, template_id: str, build_id: str) -> TemplateBuildInfo:
        payload = self._transport.request(
            "GET", f"/templates/{_id(template_id)}/build/{_id(build_id)}"
        )
        return TemplateBuildInfo.from_wire(_mapping(payload))

    def get_build_logs(self, template_id: str, build_id: str) -> Iterator[Mapping[str, Any]]:
        yield from self._transport.iter_events(
            "GET", f"/templates/{_id(template_id)}/build/{_id(build_id)}/logs"
        )

    def get_upload_link(self, template_id: str, build_id: str) -> str:
        payload = self._transport.request(
            "GET", f"/templates/{_id(template_id)}/build/{_id(build_id)}/upload-link"
        )
        body = _mapping(payload)
        value = body.get("uploadUrl", body.get("upload_url", body.get("url")))
        if not isinstance(value, str) or not value:
            raise ProtocolError("template upload response does not contain a URL")
        return value


class AsyncTemplates:
    def __init__(self, transport: AsyncTransport) -> None:
        self._transport = transport

    async def create(
        self,
        definition: Template,
        *,
        alias: str | None = None,
        idempotency_key: str | None = None,
    ) -> TemplateInfo:
        body: dict[str, object] = {"definition": definition.to_wire()}
        if alias:
            body["alias"] = alias
        payload = await self._transport.request(
            "POST",
            "/templates",
            json_body=body,
            headers={"Idempotency-Key": idempotency_key or str(uuid4())},
        )
        return TemplateInfo.from_wire(_mapping(payload))

    async def list(
        self, *, limit: int | None = None, next_token: str | None = None
    ) -> Page[TemplateInfo]:
        params: dict[str, str | int] = {}
        if limit is not None:
            params["limit"] = limit
        if next_token:
            params["nextToken"] = next_token
        return _page(await self._transport.request("GET", "/templates", params=params))

    async def get(self, template_id: str) -> TemplateInfo:
        payload = await self._transport.request("GET", f"/templates/{_id(template_id)}")
        return TemplateInfo.from_wire(_mapping(payload))

    async def get_by_alias(self, alias: str) -> TemplateInfo:
        payload = await self._transport.request("GET", f"/templates/alias/{_id(alias)}")
        return TemplateInfo.from_wire(_mapping(payload))

    async def update(self, template_id: str, *, alias: str | None) -> TemplateInfo:
        payload = await self._transport.request(
            "PATCH", f"/templates/{_id(template_id)}", json_body={"alias": alias}
        )
        return TemplateInfo.from_wire(_mapping(payload))

    async def delete(self, template_id: str) -> None:
        await self._transport.request("DELETE", f"/templates/{_id(template_id)}")

    async def build(
        self, template_id: str, *, idempotency_key: str | None = None
    ) -> TemplateBuildInfo:
        payload = await self._transport.request(
            "POST",
            f"/templates/{_id(template_id)}/build",
            headers={"Idempotency-Key": idempotency_key or str(uuid4())},
        )
        return TemplateBuildInfo.from_wire(_mapping(payload))

    async def rebuild(
        self, template_id: str, *, idempotency_key: str | None = None
    ) -> TemplateBuildInfo:
        payload = await self._transport.request(
            "POST",
            f"/templates/{_id(template_id)}/rebuild",
            headers={"Idempotency-Key": idempotency_key or str(uuid4())},
        )
        return TemplateBuildInfo.from_wire(_mapping(payload))

    async def get_build(self, template_id: str, build_id: str) -> TemplateBuildInfo:
        payload = await self._transport.request(
            "GET", f"/templates/{_id(template_id)}/build/{_id(build_id)}"
        )
        return TemplateBuildInfo.from_wire(_mapping(payload))

    async def get_build_logs(
        self, template_id: str, build_id: str
    ) -> AsyncIterator[Mapping[str, Any]]:
        async for event in self._transport.iter_events(
            "GET", f"/templates/{_id(template_id)}/build/{_id(build_id)}/logs"
        ):
            yield event

    async def get_upload_link(self, template_id: str, build_id: str) -> str:
        payload = await self._transport.request(
            "GET", f"/templates/{_id(template_id)}/build/{_id(build_id)}/upload-link"
        )
        body = _mapping(payload)
        value = body.get("uploadUrl", body.get("upload_url", body.get("url")))
        if not isinstance(value, str) or not value:
            raise ProtocolError("template upload response does not contain a URL")
        return value


def _id(value: str) -> str:
    if not value:
        raise ValueError("identifier must not be blank")
    return quote(value, safe="")


def _mapping(value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ProtocolError("template response is invalid")
    return value


def _page(value: object) -> Page[TemplateInfo]:
    if isinstance(value, list):
        source: object = value
        next_token = None
    elif isinstance(value, Mapping):
        source = value.get("templates", value.get("items", []))
        raw_token = value.get("nextToken", value.get("next_token"))
        next_token = str(raw_token) if raw_token else None
    else:
        raise ProtocolError("template list response is invalid")
    if not isinstance(source, Sequence) or isinstance(source, str | bytes):
        raise ProtocolError("template list response is invalid")
    items = tuple(TemplateInfo.from_wire(item) for item in source if isinstance(item, Mapping))
    return Page(items=items, next_token=next_token)
