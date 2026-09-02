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
    monkeypatch.delenv("E2B_API_KEY", raising=False)

    with pytest.raises(ConfigurationError, match="api_key is required"):
        ConnectionConfig.resolve()


def test_e2b_environment_names_are_supported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEVBOX_API_KEY", raising=False)
    monkeypatch.delenv("DEVBOX_API_URL", raising=False)
    monkeypatch.setenv("E2B_API_KEY", "devbox_e2b")
    monkeypatch.setenv("E2B_API_URL", "https://e2b.example.test/")

    config = ConnectionConfig.resolve()

    assert config.api_key == "devbox_e2b"
    assert config.api_url == "https://e2b.example.test"
