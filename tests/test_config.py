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


def test_api_key_is_hidden_from_configuration_repr() -> None:
    config = ConnectionConfig.resolve(api_key="devbox_secret")

    assert "devbox_secret" not in repr(config)


def test_plain_http_is_limited_to_local_development() -> None:
    local = ConnectionConfig.resolve(api_key="secret", api_url="http://localhost:8080")
    assert local.api_url == "http://localhost:8080"

    with pytest.raises(ConfigurationError, match="must use https"):
        ConnectionConfig.resolve(api_key="secret", api_url="http://api.example.test")


def test_explicit_gateway_url_takes_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEVBOX_GATEWAY_URL", "https://gateway.from-env.test")

    config = ConnectionConfig.resolve(
        api_key="secret",
        gateway_url="https://gateway.explicit.test/",
    )

    assert config.gateway_url == "https://gateway.explicit.test"
