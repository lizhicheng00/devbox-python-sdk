from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any

from devbox import GitCredentials
from devbox.commands import Commands
from devbox.git import Git


class GitTransport:
    def __init__(self) -> None:
        self.body: Mapping[str, Any] = {}

    def connect_stream(
        self,
        path: str,
        json_body: object,
        *,
        timeout: float | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Iterator[Mapping[str, Any]]:
        del path, timeout, headers
        assert isinstance(json_body, Mapping)
        self.body = json_body
        yield {"event": {"start": {"pid": 42}}}
        yield {"event": {"end": {"exited": True}}}


def test_git_credentials_are_not_embedded_in_command() -> None:
    transport = GitTransport()
    git = Git(Commands(lambda: transport))  # type: ignore[arg-type]

    git.clone(
        "https://example.test/project.git",
        "/workspace/project",
        credentials=GitCredentials("alice", "secret-token"),
    )

    process = transport.body["process"]
    assert isinstance(process, Mapping)
    command = str(process["args"])
    envs = process["envs"]
    assert "secret-token" not in command
    assert isinstance(envs, Mapping)
    assert envs["DEVBOX_GIT_PASSWORD"] == "secret-token"
