from __future__ import annotations

import pytest

from devbox import ConfigurationError
from devbox.config import ConnectionConfig


def test_api_key_can_be_read_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEVBOX_API_KEY", "devbox_from_env")
    monkeypatch.setenv("DEVBOX_API_URL", "https://api.example.test/")

    config = ConnectionConfig.resolve()

    assert config.api_key == "devbox_from_env"
    assert config.api_url == "https://api.example.test"


def test_api_key_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEVBOX_API_KEY", raising=False)

    with pytest.raises(ConfigurationError, match="api_key is required"):
        ConnectionConfig.resolve()
