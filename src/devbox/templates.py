from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from urllib.parse import quote

from ._transport import AsyncTransport, SyncTransport
from .errors import ProtocolError
from .models import (
    TemplateAliasInfo,
    TemplateBuildInfo,
    TemplateDetail,
    TemplateFileInfo,
    TemplateInfo,
)


@dataclass(frozen=True, slots=True)
class Template:
    alias: str
    name: str
    public: bool = False
    vcpu: float | None = None
    ram_mb: int | None = None
    total_disk_mb: int | None = None
    start_command: str | None = None

    def to_wire(self) -> dict[str, object]:
        body: dict[str, object] = {
            "alias": self.alias,
            "name": self.name,
            "public": self.public,
        }
        for key, value in (
            ("vcpu", self.vcpu),
            ("ram_mb", self.ram_mb),
            ("total_disk_mb", self.total_disk_mb),
            ("start_command", self.start_command),
        ):
            if value is not None:
                body[key] = value
        return body


class Templates:
    def __init__(self, transport: SyncTransport) -> None:
        self._transport = transport

    def create(self, template: Template) -> TemplateInfo:
        return TemplateInfo.from_wire(
            _object(self._transport.request("POST", "/templates", json_body=template.to_wire()))
        )

    def list(self) -> tuple[TemplateInfo, ...]:
        payload = _object(self._transport.request("GET", "/templates"))
        return tuple(TemplateInfo.from_wire(item) for item in _objects(payload.get("templates")))

    def get(self, template_id: str) -> TemplateDetail:
        return TemplateDetail.from_wire(
            _object(self._transport.request("GET", f"/templates/{_id(template_id)}"))
        )

    def get_by_alias(self, alias: str) -> TemplateAliasInfo:
        return TemplateAliasInfo.from_wire(
            _object(self._transport.request("GET", f"/templates/aliases/{_id(alias)}"))
        )

    def update(
        self, template_id: str, *, name: str | None = None, public: bool | None = None
    ) -> None:
        self._transport.request(
            "PATCH", f"/templates/{_id(template_id)}", json_body=_update_body(name, public)
        )

    def delete(self, template_id: str) -> None:
        self._transport.request("DELETE", f"/templates/{_id(template_id)}")

    def set_tags(self, target: str, tags: Sequence[str]) -> None:
        self._transport.request(
            "POST", "/templates/tags", json_body={"target": target, "tags": list(tags)}
        )

    def delete_tags(self, target: str, tags: Sequence[str]) -> None:
        self._transport.request(
            "DELETE", "/templates/tags", json_body={"target": target, "tags": list(tags)}
        )

    def list_tags(self, template_id: str) -> tuple[str, ...]:
        payload = _object(self._transport.request("GET", f"/templates/{_id(template_id)}/tags"))
        return _strings(payload.get("tags"))

    def start_build(
        self, template_id: str, build_id: str, *, compatible: bool = True
    ) -> TemplateBuildInfo:
        prefix = "/v2" if compatible else ""
        payload = self._transport.request(
            "POST", f"{prefix}/templates/{_id(template_id)}/builds/{_id(build_id)}"
        )
        return TemplateBuildInfo.from_wire(_object(payload))

    def get_build_status(self, template_id: str, build_id: str) -> TemplateBuildInfo:
        payload = self._transport.request(
            "GET", f"/templates/{_id(template_id)}/builds/{_id(build_id)}/status"
        )
        return TemplateBuildInfo.from_wire(_object(payload))

    def get_build_logs(self, template_id: str, build_id: str) -> tuple[str, ...]:
        payload = _object(
            self._transport.request(
                "GET", f"/templates/{_id(template_id)}/builds/{_id(build_id)}/logs"
            )
        )
        return _strings(payload.get("entries"))

    def get_file(self, template_id: str, content_hash: str) -> TemplateFileInfo:
        payload = self._transport.request(
            "GET", f"/templates/{_id(template_id)}/files/{_id(content_hash)}"
        )
        return TemplateFileInfo.from_wire(_object(payload))


class AsyncTemplates:
    def __init__(self, transport: AsyncTransport) -> None:
        self._transport = transport

    async def create(self, template: Template) -> TemplateInfo:
        return TemplateInfo.from_wire(
            _object(
                await self._transport.request("POST", "/templates", json_body=template.to_wire())
            )
        )

    async def list(self) -> tuple[TemplateInfo, ...]:
        payload = _object(await self._transport.request("GET", "/templates"))
        return tuple(TemplateInfo.from_wire(item) for item in _objects(payload.get("templates")))

    async def get(self, template_id: str) -> TemplateDetail:
        return TemplateDetail.from_wire(
            _object(await self._transport.request("GET", f"/templates/{_id(template_id)}"))
        )

    async def get_by_alias(self, alias: str) -> TemplateAliasInfo:
        return TemplateAliasInfo.from_wire(
            _object(await self._transport.request("GET", f"/templates/aliases/{_id(alias)}"))
        )

    async def update(
        self, template_id: str, *, name: str | None = None, public: bool | None = None
    ) -> None:
        await self._transport.request(
            "PATCH", f"/templates/{_id(template_id)}", json_body=_update_body(name, public)
        )

    async def delete(self, template_id: str) -> None:
        await self._transport.request("DELETE", f"/templates/{_id(template_id)}")

    async def set_tags(self, target: str, tags: Sequence[str]) -> None:
        await self._transport.request(
            "POST", "/templates/tags", json_body={"target": target, "tags": list(tags)}
        )

    async def delete_tags(self, target: str, tags: Sequence[str]) -> None:
        await self._transport.request(
            "DELETE", "/templates/tags", json_body={"target": target, "tags": list(tags)}
        )

    async def list_tags(self, template_id: str) -> tuple[str, ...]:
        payload = _object(
            await self._transport.request("GET", f"/templates/{_id(template_id)}/tags")
        )
        return _strings(payload.get("tags"))

    async def start_build(
        self, template_id: str, build_id: str, *, compatible: bool = True
    ) -> TemplateBuildInfo:
        prefix = "/v2" if compatible else ""
        payload = await self._transport.request(
            "POST", f"{prefix}/templates/{_id(template_id)}/builds/{_id(build_id)}"
        )
        return TemplateBuildInfo.from_wire(_object(payload))

    async def get_build_status(self, template_id: str, build_id: str) -> TemplateBuildInfo:
        payload = await self._transport.request(
            "GET", f"/templates/{_id(template_id)}/builds/{_id(build_id)}/status"
        )
        return TemplateBuildInfo.from_wire(_object(payload))

    async def get_build_logs(self, template_id: str, build_id: str) -> tuple[str, ...]:
        payload = _object(
            await self._transport.request(
                "GET", f"/templates/{_id(template_id)}/builds/{_id(build_id)}/logs"
            )
        )
        return _strings(payload.get("entries"))

    async def get_file(self, template_id: str, content_hash: str) -> TemplateFileInfo:
        payload = await self._transport.request(
            "GET", f"/templates/{_id(template_id)}/files/{_id(content_hash)}"
        )
        return TemplateFileInfo.from_wire(_object(payload))


def _update_body(name: str | None, public: bool | None) -> dict[str, object]:
    body: dict[str, object] = {}
    if name is not None:
        body["name"] = name
    if public is not None:
        body["public"] = public
    if not body:
        raise ValueError("name or public is required")
    return body


def _id(value: str) -> str:
    if not value:
        raise ValueError("identifier must not be blank")
    return quote(value, safe="")


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ProtocolError("template response is invalid")
    return value


def _objects(value: object) -> tuple[dict[str, object], ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, dict))


def _strings(value: object) -> tuple[str, ...]:
    return tuple(str(item) for item in value) if isinstance(value, list) else ()
