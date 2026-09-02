from __future__ import annotations

import shlex
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from .commands import AsyncCommands, Commands
from .models import CommandResult


@dataclass(frozen=True, slots=True)
class GitCredentials:
    username: str
    password: str = field(repr=False)

    def __post_init__(self) -> None:
        if not self.username or not self.password:
            raise ValueError("git username and password must not be blank")


class Git:
    def __init__(self, commands: Commands) -> None:
        self._commands = commands

    def clone(
        self,
        url: str,
        path: str,
        *,
        branch: str | None = None,
        depth: int | None = None,
        credentials: GitCredentials | None = None,
        timeout: float | None = 300,
    ) -> CommandResult:
        command = ["git", "clone"]
        if branch:
            command.extend(["--branch", branch])
        if depth is not None:
            if depth < 1:
                raise ValueError("git clone depth must be positive")
            command.extend(["--depth", str(depth)])
        command.extend([url, path])
        return self._run(command, credentials=credentials, timeout=timeout)

    def status(self, repository: str) -> CommandResult:
        return self._run(_in(repository, "status", "--short", "--branch"))

    def checkout(self, repository: str, reference: str, *, create: bool = False) -> CommandResult:
        arguments = ["checkout"]
        if create:
            arguments.append("-b")
        arguments.append(reference)
        return self._run(_in(repository, *arguments))

    def add(self, repository: str, paths: str | Sequence[str] = ".") -> CommandResult:
        values = [paths] if isinstance(paths, str) else list(paths)
        if not values:
            raise ValueError("at least one git path is required")
        return self._run(_in(repository, "add", "--", *values))

    def commit(self, repository: str, message: str) -> CommandResult:
        if not message.strip():
            raise ValueError("commit message must not be blank")
        return self._run(_in(repository, "commit", "-m", message))

    def pull(
        self,
        repository: str,
        *,
        remote: str = "origin",
        branch: str | None = None,
        credentials: GitCredentials | None = None,
        timeout: float | None = 300,
    ) -> CommandResult:
        command = _in(repository, "pull", remote)
        if branch:
            command.append(branch)
        return self._run(command, credentials=credentials, timeout=timeout)

    def push(
        self,
        repository: str,
        *,
        remote: str = "origin",
        branch: str | None = None,
        credentials: GitCredentials | None = None,
        timeout: float | None = 300,
    ) -> CommandResult:
        command = _in(repository, "push", remote)
        if branch:
            command.append(branch)
        return self._run(command, credentials=credentials, timeout=timeout)

    def set_config(self, repository: str, key: str, value: str) -> CommandResult:
        return self._run(_in(repository, "config", key, value))

    def _run(
        self,
        command: Sequence[str],
        *,
        credentials: GitCredentials | None = None,
        timeout: float | None = 60,
    ) -> CommandResult:
        result = self._commands.run(
            _shell_command(command, credentials),
            envs=_credential_env(credentials),
            timeout=timeout,
        )
        if not isinstance(result, CommandResult):
            raise AssertionError("foreground git command returned a background handle")
        return result


class AsyncGit:
    def __init__(self, commands: AsyncCommands) -> None:
        self._commands = commands

    async def clone(
        self,
        url: str,
        path: str,
        *,
        branch: str | None = None,
        depth: int | None = None,
        credentials: GitCredentials | None = None,
        timeout: float | None = 300,
    ) -> CommandResult:
        command = ["git", "clone"]
        if branch:
            command.extend(["--branch", branch])
        if depth is not None:
            if depth < 1:
                raise ValueError("git clone depth must be positive")
            command.extend(["--depth", str(depth)])
        command.extend([url, path])
        return await self._run(command, credentials=credentials, timeout=timeout)

    async def status(self, repository: str) -> CommandResult:
        return await self._run(_in(repository, "status", "--short", "--branch"))

    async def checkout(
        self, repository: str, reference: str, *, create: bool = False
    ) -> CommandResult:
        arguments = ["checkout"]
        if create:
            arguments.append("-b")
        arguments.append(reference)
        return await self._run(_in(repository, *arguments))

    async def add(self, repository: str, paths: str | Sequence[str] = ".") -> CommandResult:
        values = [paths] if isinstance(paths, str) else list(paths)
        if not values:
            raise ValueError("at least one git path is required")
        return await self._run(_in(repository, "add", "--", *values))

    async def commit(self, repository: str, message: str) -> CommandResult:
        if not message.strip():
            raise ValueError("commit message must not be blank")
        return await self._run(_in(repository, "commit", "-m", message))

    async def pull(
        self,
        repository: str,
        *,
        remote: str = "origin",
        branch: str | None = None,
        credentials: GitCredentials | None = None,
        timeout: float | None = 300,
    ) -> CommandResult:
        command = _in(repository, "pull", remote)
        if branch:
            command.append(branch)
        return await self._run(command, credentials=credentials, timeout=timeout)

    async def push(
        self,
        repository: str,
        *,
        remote: str = "origin",
        branch: str | None = None,
        credentials: GitCredentials | None = None,
        timeout: float | None = 300,
    ) -> CommandResult:
        command = _in(repository, "push", remote)
        if branch:
            command.append(branch)
        return await self._run(command, credentials=credentials, timeout=timeout)

    async def set_config(self, repository: str, key: str, value: str) -> CommandResult:
        return await self._run(_in(repository, "config", key, value))

    async def _run(
        self,
        command: Sequence[str],
        *,
        credentials: GitCredentials | None = None,
        timeout: float | None = 60,
    ) -> CommandResult:
        result = await self._commands.run(
            _shell_command(command, credentials),
            envs=_credential_env(credentials),
            timeout=timeout,
        )
        if not isinstance(result, CommandResult):
            raise AssertionError("foreground git command returned a background handle")
        return result


def _in(repository: str, *arguments: str) -> list[str]:
    if not repository:
        raise ValueError("repository path must not be blank")
    return ["git", "-C", repository, *arguments]


def _shell_command(command: Sequence[str], credentials: GitCredentials | None) -> str:
    arguments = list(command)
    if credentials:
        arguments[1:1] = [
            "-c",
            "credential.helper=!f() { printf '%s\\n' "
            '"username=$DEVBOX_GIT_USERNAME" '
            '"password=$DEVBOX_GIT_PASSWORD"; }; f',
            "-c",
            "credential.useHttpPath=true",
        ]
    return " ".join(shlex.quote(argument) for argument in arguments)


def _credential_env(credentials: GitCredentials | None) -> Mapping[str, str] | None:
    if credentials is None:
        return None
    return {
        "DEVBOX_GIT_USERNAME": credentials.username,
        "DEVBOX_GIT_PASSWORD": credentials.password,
        "GIT_TERMINAL_PROMPT": "0",
    }
