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
class NetworkRule:
    headers: Mapping[str, str] = field(default_factory=dict)

    def to_wire(self) -> dict[str, object]:
        return {"transform": {"headers": dict(self.headers)}}


@dataclass(frozen=True, slots=True)
class NetworkConfig:
    allow_internet_access: bool = True
    allow_public_traffic: bool = False
    allow_out: tuple[str, ...] = ()
    deny_out: tuple[str, ...] = ()
    mask_request_host: str | None = None
    rules: Mapping[str, tuple[NetworkRule, ...]] = field(default_factory=dict)

    def to_create_wire(self) -> dict[str, object]:
        value: dict[str, object] = {
            "allowPublicTraffic": self.allow_public_traffic,
            "allowOut": list(self.allow_out),
            "denyOut": list(self.deny_out),
            "rules": _rules_to_wire(self.rules),
        }
        if self.mask_request_host is not None:
            value["maskRequestHost"] = self.mask_request_host
        return value

    def to_update_wire(self) -> dict[str, object]:
        return {
            "allowOut": list(self.allow_out),
            "denyOut": list(self.deny_out),
            "rules": _rules_to_wire(self.rules),
            "allow_internet_access": self.allow_internet_access,
        }

    @classmethod
    def from_wire(cls, value: object, *, allow_internet_access: bool = True) -> NetworkConfig:
        if not isinstance(value, Mapping):
            return cls(allow_internet_access=allow_internet_access)
        return cls(
            allow_internet_access=allow_internet_access,
            allow_public_traffic=bool(value.get("allowPublicTraffic", True)),
            allow_out=_string_tuple(value.get("allowOut")),
            deny_out=_string_tuple(value.get("denyOut")),
            mask_request_host=_optional_str(value.get("maskRequestHost")),
            rules=_rules_from_wire(value.get("rules")),
        )


@dataclass(frozen=True, slots=True)
class VolumeMount:
    name: str
    path: str

    def to_wire(self) -> dict[str, str]:
        return {"name": self.name, "path": self.path}

    @classmethod
    def from_wire(cls, value: Mapping[str, Any]) -> VolumeMount:
        return cls(name=str(_pick(value, "name")), path=str(_pick(value, "path")))


@dataclass(frozen=True, slots=True)
class SandboxLifecycle:
    auto_resume: bool
    on_timeout: str

    @classmethod
    def from_wire(cls, value: object) -> SandboxLifecycle | None:
        if not isinstance(value, Mapping):
            return None
        return cls(
            auto_resume=bool(value.get("autoResume", False)),
            on_timeout=str(value.get("onTimeout", "kill")),
        )


@dataclass(frozen=True, slots=True)
class SandboxInfo:
    sandbox_id: str
    template_id: str
    state: SandboxState
    client_id: str = ""
    alias: str | None = None
    started_at: datetime | None = None
    end_at: datetime | None = None
    envd_version: str = ""
    cpu_count: int | None = None
    memory_mb: int | None = None
    disk_size_mb: int | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)
    network: NetworkConfig = field(default_factory=NetworkConfig)
    lifecycle: SandboxLifecycle | None = None
    volume_mounts: tuple[VolumeMount, ...] = ()

    @classmethod
    def from_wire(cls, value: Mapping[str, Any]) -> SandboxInfo:
        return cls(
            sandbox_id=str(_pick(value, "sandboxId", "sandboxID", "sandbox_id", "id")),
            template_id=str(
                _pick(value, "templateId", "templateID", "template_id", default="base")
            ),
            state=SandboxState(str(_pick(value, "state", "status", default="running"))),
            client_id=str(_pick(value, "clientID", "client_id", default="")),
            alias=_optional_str(value.get("alias")),
            started_at=parse_optional_datetime(
                _pick(value, "createdAt", "created_at", "startedAt", "started_at", default=None)
            ),
            end_at=parse_optional_datetime(
                _pick(value, "expiresAt", "expires_at", "endAt", "end_at", default=None)
            ),
            envd_version=str(_pick(value, "envdVersion", "envd_version", default="")),
            cpu_count=_optional_int(value.get("cpuCount")),
            memory_mb=_optional_int(value.get("memoryMB")),
            disk_size_mb=_optional_int(value.get("diskSizeMB")),
            metadata=_string_map(value.get("metadata")),
            network=NetworkConfig.from_wire(
                value.get("network"),
                allow_internet_access=bool(value.get("allowInternetAccess", True)),
            ),
            lifecycle=SandboxLifecycle.from_wire(value.get("lifecycle")),
            volume_mounts=tuple(
                VolumeMount.from_wire(item) for item in _mapping_items(value.get("volumeMounts"))
            ),
        )

    @property
    def created_at(self) -> datetime | None:
        return self.started_at

    @property
    def expires_at(self) -> datetime | None:
        return self.end_at


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
                    default="",
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
    timestamp_unix: int
    cpu_count: int
    cpu_used_percent: float
    memory_used_bytes: int
    memory_total_bytes: int
    memory_cache_bytes: int
    disk_used_bytes: int
    disk_total_bytes: int
    timestamp: datetime | None = None

    @classmethod
    def from_wire(cls, value: Mapping[str, Any]) -> SandboxMetrics:
        return cls(
            timestamp_unix=_integer(_pick(value, "timestampUnix")),
            cpu_count=_integer(_pick(value, "cpuCount")),
            cpu_used_percent=_number(_pick(value, "cpuUsedPct")),
            memory_used_bytes=_integer(_pick(value, "memUsed")),
            memory_total_bytes=_integer(_pick(value, "memTotal")),
            memory_cache_bytes=_integer(_pick(value, "memCache")),
            disk_used_bytes=_integer(_pick(value, "diskUsed")),
            disk_total_bytes=_integer(_pick(value, "diskTotal")),
            timestamp=parse_optional_datetime(value.get("timestamp")),
        )


@dataclass(frozen=True, slots=True)
class SnapshotInfo:
    snapshot_id: str
    names: tuple[str, ...]

    @classmethod
    def from_wire(cls, value: Mapping[str, Any]) -> SnapshotInfo:
        return cls(
            snapshot_id=str(_pick(value, "snapshotID", "snapshotId", "snapshot_id", "id")),
            names=_string_tuple(value.get("names")),
        )


class LogLevel(str, Enum):
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"
    DEBUG = "DEBUG"
    TRACE = "TRACE"


class LogsDirection(str, Enum):
    BACKWARD = "backward"
    FORWARD = "forward"


@dataclass(frozen=True, slots=True)
class SandboxLogEntry:
    timestamp: datetime
    level: LogLevel
    message: str
    fields: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def from_wire(cls, value: Mapping[str, Any]) -> SandboxLogEntry:
        return cls(
            timestamp=parse_datetime(_pick(value, "timestamp")),
            level=LogLevel(str(_pick(value, "level"))),
            message=str(_pick(value, "message")),
            fields=_string_map(value.get("fields")),
        )


@dataclass(frozen=True, slots=True)
class ProcessInfo:
    pid: int
    command: str
    running: bool
    started_at: datetime | None = None

    @classmethod
    def from_wire(cls, value: Mapping[str, Any]) -> ProcessInfo:
        config = value.get("config")
        process = config if isinstance(config, Mapping) else value
        cmd = str(_pick(process, "command", "cmd", default=""))
        args = _string_tuple(process.get("args"))
        return cls(
            pid=_integer(_pick(value, "pid")),
            command=" ".join((cmd, *args)).strip(),
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
        file_type = {
            "FILE_TYPE_FILE": FileType.FILE,
            "FILE_TYPE_DIRECTORY": FileType.DIRECTORY,
            "FILE_TYPE_SYMLINK": FileType.SYMLINK,
        }.get(str(_pick(value, "type", default="file")))
        return cls(
            name=str(_pick(value, "name")),
            path=str(_pick(value, "path")),
            type=file_type or FileType(str(_pick(value, "type", default="file"))),
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
    namespace: str
    name: str | None = None
    public: bool = False
    created_by: str | None = None
    spawn_count: int = 0
    created_at: datetime | None = None

    @classmethod
    def from_wire(cls, value: Mapping[str, Any]) -> TemplateInfo:
        return cls(
            template_id=str(_pick(value, "template_id", "templateID", "templateId", "id")),
            namespace=str(_pick(value, "namespace")),
            name=_optional_str(value.get("name")),
            public=bool(value.get("public", False)),
            created_by=_optional_str(value.get("created_by")),
            spawn_count=_integer(value.get("spawn_count", 0)),
            created_at=parse_optional_datetime(value.get("created_at")),
        )


@dataclass(frozen=True, slots=True)
class TemplateBuildInfo:
    template_id: str
    build_id: str
    namespace: str | None = None
    status: str | None = None
    tag: str | None = None
    vcpu: float | None = None
    ram_mb: int | None = None
    total_disk_mb: int | None = None
    kernel_version: str | None = None
    firecracker_version: str | None = None
    reason: str | None = None
    created_at: datetime | None = None

    @classmethod
    def from_wire(cls, value: Mapping[str, Any]) -> TemplateBuildInfo:
        return cls(
            template_id=str(_pick(value, "template_id", "templateID", "templateId")),
            build_id=str(_pick(value, "build_id", "buildID", "buildId", "id")),
            namespace=_optional_str(value.get("namespace")),
            status=_optional_str(value.get("status")),
            tag=_optional_str(value.get("tag")),
            vcpu=_optional_number(value.get("vcpu")),
            ram_mb=_optional_int(value.get("ram_mb")),
            total_disk_mb=_optional_int(value.get("total_disk_mb")),
            kernel_version=_optional_str(value.get("kernel_version")),
            firecracker_version=_optional_str(value.get("firecracker_version")),
            reason=_optional_str(value.get("reason")),
            created_at=parse_optional_datetime(value.get("created_at")),
        )


@dataclass(frozen=True, slots=True)
class TemplateDetail:
    template: TemplateInfo
    builds: tuple[TemplateBuildInfo, ...] = ()

    @classmethod
    def from_wire(cls, value: Mapping[str, Any]) -> TemplateDetail:
        return cls(
            template=TemplateInfo.from_wire(_required_mapping(value.get("template"))),
            builds=tuple(
                TemplateBuildInfo.from_wire(item) for item in _mapping_items(value.get("builds"))
            ),
        )


@dataclass(frozen=True, slots=True)
class TemplateAliasInfo:
    alias: str
    template_id: str
    namespace: str

    @classmethod
    def from_wire(cls, value: Mapping[str, Any]) -> TemplateAliasInfo:
        return cls(
            alias=str(_pick(value, "alias")),
            template_id=str(_pick(value, "template_id")),
            namespace=str(_pick(value, "namespace")),
        )


@dataclass(frozen=True, slots=True)
class TemplateFileInfo:
    exists: bool
    upload_url: str | None = None

    @classmethod
    def from_wire(cls, value: Mapping[str, Any]) -> TemplateFileInfo:
        return cls(
            exists=bool(value.get("exists", False)),
            upload_url=_optional_str(value.get("upload_url")),
        )


class NodeStatus(str, Enum):
    READY = "ready"
    DRAINING = "draining"
    OFFLINE = "offline"


@dataclass(frozen=True, slots=True)
class NodeInfo:
    node_id: str
    node_name: str | None = None
    cluster_id: str | None = None
    ip_address: str | None = None
    cpu_total: float | None = None
    cpu_free: float | None = None
    ram_total_mb: int | None = None
    ram_free_mb: int | None = None
    disk_total_mb: int | None = None
    disk_free_mb: int | None = None
    current_sandbox_count: int | None = None
    status: str | None = None

    @classmethod
    def from_wire(cls, value: Mapping[str, Any]) -> NodeInfo:
        return cls(
            node_id=str(_pick(value, "node_id")),
            node_name=_optional_str(value.get("node_name")),
            cluster_id=_optional_str(value.get("cluster_id")),
            ip_address=_optional_str(value.get("ip_address")),
            cpu_total=_optional_number(value.get("cpu_total")),
            cpu_free=_optional_number(value.get("cpu_free")),
            ram_total_mb=_optional_int(value.get("ram_total_mb")),
            ram_free_mb=_optional_int(value.get("ram_free_mb")),
            disk_total_mb=_optional_int(value.get("disk_total_mb")),
            disk_free_mb=_optional_int(value.get("disk_free_mb")),
            current_sandbox_count=_optional_int(value.get("current_sandbox_count")),
            status=_optional_str(value.get("status")),
        )


@dataclass(frozen=True, slots=True)
class HealthInfo:
    status: str
    message: str | None = None

    @classmethod
    def from_wire(cls, value: Mapping[str, Any]) -> HealthInfo:
        return cls(
            status=str(_pick(value, "status")),
            message=_optional_str(value.get("message")),
        )


T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class Page(Generic[T]):
    items: tuple[T, ...]
    next_token: str | None = None
    total: int | None = None


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


def _optional_str(value: object) -> str | None:
    return None if value is None else str(value)


def _optional_int(value: object) -> int | None:
    return None if value is None else _integer(value)


def _optional_number(value: object) -> float | None:
    return None if value is None else _number(value)


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list | tuple):
        return ()
    return tuple(str(item) for item in value)


def _mapping_items(value: object) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, list | tuple):
        return ()
    return tuple(item for item in value if isinstance(item, Mapping))


def _required_mapping(value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("response field is not an object")
    return value


def _rules_to_wire(
    value: Mapping[str, tuple[NetworkRule, ...]],
) -> dict[str, list[dict[str, object]]]:
    return {key: [rule.to_wire() for rule in rules] for key, rules in value.items()}


def _rules_from_wire(value: object) -> Mapping[str, tuple[NetworkRule, ...]]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, tuple[NetworkRule, ...]] = {}
    for key, rules in value.items():
        parsed: list[NetworkRule] = []
        for item in _mapping_items(rules):
            transform = item.get("transform")
            headers = transform.get("headers") if isinstance(transform, Mapping) else None
            parsed.append(NetworkRule(headers=_string_map(headers)))
        result[str(key)] = tuple(parsed)
    return result


def _gateway_url(value: Mapping[str, Any]) -> str:
    raw = str(
        _pick(
            value,
            "gatewayUrl",
            "gateway_url",
            "envdUrl",
            "envd_url",
            "domain",
            default="",
        )
    )
    if not raw or raw == "None":
        return ""
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
