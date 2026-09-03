from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from .errors import ConfigurationError

DEFAULT_API_URL = "https://devbox.developer.myhuaweicloud.com"


@dataclass(frozen=True, slots=True)
class ConnectionConfig:
    """Connection settings shared by control-plane requests."""

    api_key: str = field(repr=False)
    api_url: str = DEFAULT_API_URL
    gateway_url: str | None = None
    request_timeout: float = 30.0
    headers: Mapping[str, str] = field(default_factory=dict, repr=False)

    @classmethod
    def resolve(
        cls,
        *,
        api_key: str | None = None,
        api_url: str | None = None,
        gateway_url: str | None = None,
        request_timeout: float = 30.0,
        headers: Mapping[str, str] | None = None,
    ) -> ConnectionConfig:
        resolved_key = (
            api_key or os.getenv("DEVBOX_API_KEY") or os.getenv("E2B_API_KEY") or ""
        ).strip()
        if not resolved_key:
            raise ConfigurationError(
                "api_key is required; set DEVBOX_API_KEY, E2B_API_KEY, or pass api_key"
            )
        resolved_api_url = (
            api_url or os.getenv("DEVBOX_API_URL") or os.getenv("E2B_API_URL") or DEFAULT_API_URL
        )
        resolved_gateway_url = gateway_url or os.getenv("DEVBOX_GATEWAY_URL") or None
        if request_timeout <= 0:
            raise ConfigurationError("request_timeout must be positive")
        return cls(
            api_key=resolved_key,
            api_url=_service_url(resolved_api_url, "api_url"),
            gateway_url=(
                _service_url(resolved_gateway_url, "gateway_url") if resolved_gateway_url else None
            ),
            request_timeout=request_timeout,
            headers=dict(headers or {}),
        )


def _service_url(value: str, name: str) -> str:
    url = value.strip().rstrip("/")
    parsed = urlsplit(url)
    if parsed.scheme == "https" and parsed.netloc:
        return url
    if parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}:
        return url
    raise ConfigurationError(f"{name} must use https (http is allowed only for localhost)")
