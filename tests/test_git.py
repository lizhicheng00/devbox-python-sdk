from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any

from devbox import GitCredentials
from devbox.commands import Commands
from devbox.git import Git


class GitTransport:
    def __init__(self) -> None:
        self.body: Mapping[str, Any] = {}

    def iter_events(
        self, method: str, path: str, *, json_body: object | None = None
    ) -> Iterator[Mapping[str, Any]]:
        assert isinstance(json_body, Mapping)
        self.body = json_body
        yield {"type": "exit", "exitCode": 0}


def test_git_credentials_are_not_embedded_in_command() -> None:
    transport = GitTransport()
    git = Git(Commands(lambda: transport))  # type: ignore[arg-type]

    git.clone(
        "https://example.test/project.git",
        "/workspace/project",
        credentials=GitCredentials("alice", "secret-token"),
    )

    command = str(transport.body["command"])
    envs = transport.body["envs"]
    assert "secret-token" not in command
    assert isinstance(envs, Mapping)
    assert envs["DEVBOX_GIT_PASSWORD"] == "secret-token"
