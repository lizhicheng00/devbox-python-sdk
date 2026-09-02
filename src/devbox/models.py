from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Generic, TypeVar


class SandboxState(str, Enum):
    CREATING = "creating"
    RUNNING = "running"
    PAUSING = "pausing"
    PAUSED = "paused"
    RESUMING = "resuming"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


class LifecycleEventType(str, Enum):
    CREATED = "created"
    UPDATED = "updated"
    PAUSED = "paused"
    RESUMED = "resumed"
    CHECKPOINTED = "checkpointed"
    KILLED = "killed"


class FileType(str, Enum):
    FILE = "file"
    DIRECTORY = "directory"
    SYMLINK = "symlink"


class TemplateBuildStatus(str, Enum):
    QUEUED = "queued"
    BUILDING = "building"
    READY = "ready"
    FAILED = "failed"
    CANCELED = "canceled"


@dataclass(frozen=True, slots=True)
class NetworkConfig:
    allow_internet_access: bool = True
    allow_public_traffic: bool = False

    def to_wire(self) -> dict[str, bool]:
        return {
            "allowInternetAccess": self.allow_internet_access,
            "allowPublicTraffic": self.allow_public_traffic,
        }


@dataclass(frozen=True, slots=True)
class SandboxInfo:
    sandbox_id: str
    template_id: str
    state: SandboxState
    created_at: datetime | None = None
    updated_at: datetime | None = None
    timeout: int | None = None
    expires_at: datetime | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)
    network: NetworkConfig = field(default_factory=NetworkConfig)

    @classmethod
    def from_wire(cls, value: Mapping[str, Any]) -> SandboxInfo:
        return cls(
            sandbox_id=str(_pick(value, "sandboxId", "sandboxID", "sandbox_id", "id")),
            template_id=str(
                _pick(value, "templateId", "templateID", "template_id", default="base")
            ),
            state=SandboxState(str(_pick(value, "state", "status", default="running"))),
            created_at=parse_optional_datetime(
                _pick(value, "createdAt", "created_at", "startedAt", "started_at", default=None)
            ),
            updated_at=parse_optional_datetime(
                _pick(value, "updatedAt", "updated_at", default=None)
            ),
            timeout=_optional_int(_pick(value, "timeout", default=None)),
            expires_at=parse_optional_datetime(
                _pick(value, "expiresAt", "expires_at", "endAt", "end_at", default=None)
            ),
            metadata=_string_map(value.get("metadata")),
            network=_network(value.get("network")),
        )


@dataclass(frozen=True, slots=True)
class SandboxConnection:
    sandbox_id: str
    gateway_url: str
    access_token: str = field(repr=False)
    expires_at: datetime | None = None
    protocol_version: str = "v1"

    @classmethod
    def from_wire(cls, value: Mapping[str, Any], sandbox_id: str) -> SandboxConnection:
        return cls(
            sandbox_id=sandbox_id,
            gateway_url=_gateway_url(value),
            access_token=str(
                _pick(
                    value,
                    "accessToken",
                    "access_token",
                    "envdAccessToken",
                    "envd_access_token",
                    "token",
                )
            ),
            expires_at=parse_optional_datetime(
                _pick(value, "expiresAt", "expires_at", default=None)
            ),
            protocol_version=str(
                _pick(
                    value,
                    "protocolVersion",
                    "protocol_version",
                    "envdVersion",
                    "envd_version",
                    default="v1",
                )
            ),
        )


@dataclass(frozen=True, slots=True)
class SandboxMetrics:
    timestamp: datetime
    cpu_percent: float
    memory_used_bytes: int
    memory_total_bytes: int
    disk_used_bytes: int
    disk_total_bytes: int

    @classmethod
    def from_wire(cls, value: Mapping[str, Any]) -> SandboxMetrics:
        return cls(
            timestamp=parse_datetime(_pick(value, "timestamp")),
            cpu_percent=_number(_pick(value, "cpuPercent", "cpu_percent", default=0)),
            memory_used_bytes=_integer(
                _pick(value, "memoryUsedBytes", "memory_used_bytes", default=0)
            ),
            memory_total_bytes=_integer(
                _pick(value, "memoryTotalBytes", "memory_total_bytes", default=0)
            ),
            disk_used_bytes=_integer(_pick(value, "diskUsedBytes", "disk_used_bytes", default=0)),
            disk_total_bytes=_integer(
                _pick(value, "diskTotalBytes", "disk_total_bytes", default=0)
            ),
        )


@dataclass(frozen=True, slots=True)
class SnapshotInfo:
    snapshot_id: str
    sandbox_id: str
    created_at: datetime

    @classmethod
    def from_wire(cls, value: Mapping[str, Any]) -> SnapshotInfo:
        return cls(
            snapshot_id=str(_pick(value, "snapshotId", "snapshot_id", "id")),
            sandbox_id=str(_pick(value, "sandboxId", "sandbox_id")),
            created_at=parse_datetime(_pick(value, "createdAt", "created_at")),
        )


@dataclass(frozen=True, slots=True)
class ProcessInfo:
    pid: int
    command: str
    running: bool
    started_at: datetime | None = None

    @classmethod
    def from_wire(cls, value: Mapping[str, Any]) -> ProcessInfo:
        return cls(
            pid=_integer(_pick(value, "pid")),
            command=str(_pick(value, "command", "cmd", default="")),
            running=bool(_pick(value, "running", default=True)),
            started_at=parse_optional_datetime(
                _pick(value, "startedAt", "started_at", default=None)
            ),
        )


@dataclass(frozen=True, slots=True)
class OutputChunk:
    stream: str
    data: str
    timestamp: datetime | None = None


@dataclass(frozen=True, slots=True)
class CommandResult:
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    pid: int | None = None


@dataclass(frozen=True, slots=True)
class PtySize:
    rows: int = 24
    cols: int = 80

    def __post_init__(self) -> None:
        if self.rows < 1 or self.cols < 1:
            raise ValueError("PTY rows and cols must be positive")


@dataclass(frozen=True, slots=True)
class FileInfo:
    name: str
    path: str
    type: FileType
    size: int
    mode: int | None = None
    permissions: str | None = None
    owner: str | None = None
    group: str | None = None
    modified_at: datetime | None = None
    symlink_target: str | None = None

    @classmethod
    def from_wire(cls, value: Mapping[str, Any]) -> FileInfo:
        return cls(
            name=str(_pick(value, "name")),
            path=str(_pick(value, "path")),
            type=FileType(str(_pick(value, "type", default="file"))),
            size=_integer(_pick(value, "size", default=0)),
            mode=_optional_int(value.get("mode")),
            permissions=_optional_str(value.get("permissions")),
            owner=_optional_str(value.get("owner")),
            group=_optional_str(value.get("group")),
            modified_at=parse_optional_datetime(
                _pick(value, "modifiedTime", "modifiedAt", "modified_at", default=None)
            ),
            symlink_target=_optional_str(
                _pick(value, "symlinkTarget", "symlink_target", default=None)
            ),
        )


@dataclass(frozen=True, slots=True)
class TemplateInfo:
    template_id: str
    alias: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_wire(cls, value: Mapping[str, Any]) -> TemplateInfo:
        return cls(
            template_id=str(_pick(value, "templateId", "template_id", "id")),
            alias=_optional_str(value.get("alias")),
            created_at=parse_datetime(_pick(value, "createdAt", "created_at")),
            updated_at=parse_datetime(_pick(value, "updatedAt", "updated_at")),
        )


@dataclass(frozen=True, slots=True)
class TemplateBuildInfo:
    template_id: str
    build_id: str
    status: TemplateBuildStatus
    created_at: datetime

    @classmethod
    def from_wire(cls, value: Mapping[str, Any]) -> TemplateBuildInfo:
        return cls(
            template_id=str(_pick(value, "templateId", "template_id")),
            build_id=str(_pick(value, "buildId", "build_id", "id")),
            status=TemplateBuildStatus(str(_pick(value, "status"))),
            created_at=parse_datetime(_pick(value, "createdAt", "created_at")),
        )


T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class Page(Generic[T]):
    items: tuple[T, ...]
    next_token: str | None = None


def parse_datetime(value: object) -> datetime:
    parsed = parse_optional_datetime(value)
    if parsed is None:
        raise ValueError("timestamp is required")
    return parsed


def parse_optional_datetime(value: object) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, int | float):
        return datetime.fromtimestamp(value, timezone.utc)
    text = str(value).replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _pick(value: Mapping[str, Any], *keys: str, default: object = ...) -> object:
    for key in keys:
        if key in value:
            return value[key]
    if default is not ...:
        return default
    raise ValueError(f"response field is missing: {keys[0]}")


def _string_map(value: object) -> Mapping[str, str]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): str(item) for key, item in value.items()}


def _network(value: object) -> NetworkConfig:
    if not isinstance(value, Mapping):
        return NetworkConfig()
    return NetworkConfig(
        allow_internet_access=bool(
            _pick(value, "allowInternetAccess", "allow_internet_access", default=True)
        ),
        allow_public_traffic=bool(
            _pick(value, "allowPublicTraffic", "allow_public_traffic", default=False)
        ),
    )


def _optional_str(value: object) -> str | None:
    return None if value is None else str(value)


def _optional_int(value: object) -> int | None:
    return None if value is None else _integer(value)


def _gateway_url(value: Mapping[str, Any]) -> str:
    raw = str(_pick(value, "gatewayUrl", "gateway_url", "envdUrl", "envd_url", "domain"))
    if not raw or raw == "None":
        raise ValueError("sandbox response does not contain a gateway URL")
    return raw if raw.startswith(("http://", "https://")) else f"https://{raw}"


def _integer(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str | bytes | bytearray):
        return int(value)
    raise ValueError("response value is not an integer")


def _number(value: object) -> float:
    if isinstance(value, int | float | str | bytes | bytearray):
        return float(value)
    raise ValueError("response value is not a number")
