from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field

from .errors import ConfigurationError

DEFAULT_API_URL = "https://devbox.developer.myhuaweicloud.com"


@dataclass(frozen=True, slots=True)
class ConnectionConfig:
    """Connection settings shared by control-plane requests."""

    api_key: str
    api_url: str = DEFAULT_API_URL
    request_timeout: float = 30.0
    headers: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def resolve(
        cls,
        *,
        api_key: str | None = None,
        api_url: str | None = None,
        request_timeout: float = 30.0,
        headers: Mapping[str, str] | None = None,
    ) -> ConnectionConfig:
        resolved_key = (api_key or os.getenv("DEVBOX_API_KEY") or "").strip()
        if not resolved_key:
            raise ConfigurationError("api_key is required; set DEVBOX_API_KEY or pass api_key")
        resolved_url = (api_url or os.getenv("DEVBOX_API_URL") or DEFAULT_API_URL).rstrip("/")
        if not resolved_url.startswith(("https://", "http://")):
            raise ConfigurationError("api_url must start with http:// or https://")
        if request_timeout <= 0:
            raise ConfigurationError("request_timeout must be positive")
        return cls(
            api_key=resolved_key,
            api_url=resolved_url,
            request_timeout=request_timeout,
            headers=dict(headers or {}),
        )
