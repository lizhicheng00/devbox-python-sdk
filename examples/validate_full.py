from __future__ import annotations

import os
import queue
import tempfile
import threading
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TypeVar
from uuid import uuid4

from devbox import CommandResult, DevBox, DevBoxError, NetworkConfig, PtySize, Sandbox

T = TypeVar("T")


class Validator:
    def __init__(self) -> None:
        self.failures: list[str] = []

    def verify(self, name: str, operation: Callable[[], T]) -> T | None:
        try:
            result = operation()
        except Exception as error:
            self.failures.append(name)
            print(f"FAIL {name}: {error}")
            return None
        print(f"PASS {name}")
        return result

    @staticmethod
    def skip(name: str, reason: str) -> None:
        print(f"SKIP {name}: {reason}")


def main() -> None:
    template = os.getenv("DEVBOX_TEST_TEMPLATE", "default").strip() or "default"
    validator = Validator()

    with DevBox() as client:
        sandbox = validator.verify(
            "sandbox.create",
            lambda: client.sandboxes.create(
                template,
                timeout=300,
                metadata={"sdk_validation": "full"},
                network=NetworkConfig(allow_internet_access=True),
            ),
        )
        if sandbox is None:
            raise SystemExit("Full validation stopped because sandbox creation failed")

        print(f"Sandbox ready: {sandbox.sandbox_id}")
        try:
            validate_manager(client, sandbox, validator)
            runtime_ready = validator.verify(
                "runtime.ready",
                lambda: _validate_runtime_ready(sandbox),
            )
            if runtime_ready is None:
                for area in ("commands", "filesystem", "pty", "git"):
                    validator.skip(area, "runtime gateway is unavailable")
            else:
                validate_commands(sandbox, validator)
                validate_filesystem(sandbox, validator)
                validate_pty(sandbox, validator)
                validate_git(sandbox, validator)
        finally:
            validator.verify("sandbox.delete", sandbox.kill)
            sandbox.close()

    if validator.failures:
        names = ", ".join(validator.failures)
        raise SystemExit(f"Full validation failed ({len(validator.failures)}): {names}")
    print("DevBox phase-one full validation passed")


def validate_manager(client: DevBox, sandbox: Sandbox, validator: Validator) -> None:
    validator.verify("manager.get", lambda: _expect_id(sandbox.get_info(), sandbox.sandbox_id))
    validator.verify("manager.is_running", lambda: _expect(sandbox.is_running(), "not running"))
    validator.verify(
        "manager.list",
        lambda: _expect(
            sandbox.sandbox_id
            in {item.sandbox_id for item in client.sandboxes.list(limit=100).items},
            "created sandbox is missing from list",
        ),
    )
    validator.verify("manager.set_timeout", lambda: sandbox.set_timeout(300))
    validator.verify("manager.refresh", lambda: sandbox.refresh(300))
    validator.verify("manager.metrics", sandbox.get_metrics)
    validator.verify(
        "manager.aggregate_metrics",
        lambda: client.sandboxes.metrics([sandbox.sandbox_id]),
    )
    validator.verify("manager.logs", lambda: sandbox.get_logs(limit=20))
    validator.verify(
        "manager.update_network",
        lambda: sandbox.update_network(NetworkConfig(allow_internet_access=True)),
    )
    validator.verify("manager.pause_resume", lambda: validate_pause_resume(sandbox))


def validate_commands(sandbox: Sandbox, validator: Validator) -> None:
    validator.verify(
        "commands.foreground",
        lambda: _expect_result(sandbox.commands.run("printf command-ok"), stdout="command-ok"),
    )
    validator.verify(
        "commands.options",
        lambda: _expect_result(
            sandbox.commands.run(
                'printf "$DEVBOX_FULL_TEST"; printf error-ok >&2',
                cwd="/tmp",
                envs={"DEVBOX_FULL_TEST": "env-ok"},
            ),
            stdout="env-ok",
            stderr="error-ok",
        ),
    )
    validator.verify("commands.background", lambda: _validate_background(sandbox))
    validator.verify("commands.stdin", lambda: _validate_stdin(sandbox))
    validator.verify("commands.signal", lambda: _validate_signal(sandbox))
    validator.verify("commands.reconnect", lambda: _validate_reconnect(sandbox))


def _validate_runtime_ready(sandbox: Sandbox) -> bool:
    _expect_result(sandbox.commands.run("printf runtime-ready"), stdout="runtime-ready")
    return True


def _validate_background(sandbox: Sandbox) -> None:
    handle = sandbox.commands.run("sleep 1; printf background-ok", background=True, timeout=10)
    processes = sandbox.commands.list()
    _expect(handle.pid in {process.pid for process in processes}, "process is missing from list")
    _expect_result(handle.wait(), stdout="background-ok")


def _validate_stdin(sandbox: Sandbox) -> None:
    handle = sandbox.commands.run("cat", background=True, stdin=True, timeout=10)
    handle.send_stdin("stdin-ok\n")
    handle.close_stdin()
    _expect_result(handle.wait(), stdout="stdin-ok\n")


def _validate_signal(sandbox: Sandbox) -> None:
    handle = sandbox.commands.run("sleep 30", background=True, timeout=35)
    handle.send_signal("SIGTERM")
    result = handle.wait(check=False)
    _expect(result.exit_code != 0, "signalled process exited successfully")


def _validate_reconnect(sandbox: Sandbox) -> None:
    handle = sandbox.commands.run("cat", background=True, stdin=True, timeout=10)
    pid = handle.pid
    handle.disconnect()
    connected = sandbox.commands.connect(pid, timeout=10)
    connected.send_stdin("reconnect-ok\n")
    connected.close_stdin()
    _expect_result(connected.wait(), stdout="reconnect-ok\n")


def validate_filesystem(sandbox: Sandbox, validator: Validator) -> None:
    root = f"/tmp/devbox-sdk-full-{uuid4().hex[:8]}"
    validator.verify("filesystem.basic", lambda: _validate_filesystem_basic(sandbox, root))
    validator.verify("filesystem.transfer", lambda: _validate_transfer(sandbox, root))
    validator.verify("filesystem.watch", lambda: _validate_watch(sandbox, root))
    validator.verify("filesystem.remove", lambda: sandbox.files.remove(root))


def _validate_filesystem_basic(sandbox: Sandbox, root: str) -> None:
    sandbox.files.make_dir(root)
    text_path = f"{root}/message.txt"
    binary_path = f"{root}/data.bin"
    sandbox.files.write_batch({text_path: "file-ok", binary_path: b"\x00\x01\x02"})
    _expect(sandbox.files.read(text_path) == "file-ok", "text content differs")
    _expect(sandbox.files.read_bytes(binary_path) == b"\x00\x01\x02", "binary content differs")
    _expect(sandbox.files.exists(text_path), "written file does not exist")
    _expect(sandbox.files.stat(text_path).size == 7, "file size differs")
    _expect(len(sandbox.files.list(root, depth=2)) >= 2, "directory listing is incomplete")
    moved_path = f"{root}/moved.txt"
    sandbox.files.move(text_path, moved_path)
    _expect(sandbox.files.exists(moved_path), "moved file does not exist")
    _expect(not sandbox.files.exists(text_path), "source still exists after move")


def _validate_transfer(sandbox: Sandbox, root: str) -> None:
    with tempfile.TemporaryDirectory() as local_directory:
        source = Path(local_directory, "upload.txt")
        destination = Path(local_directory, "download.txt")
        source.write_text("transfer-ok", encoding="utf-8")
        sandbox.files.upload(source, f"{root}/upload.txt")
        sandbox.files.download(f"{root}/upload.txt", destination)
        _expect(destination.read_text(encoding="utf-8") == "transfer-ok", "download differs")


def _validate_watch(sandbox: Sandbox, root: str) -> None:
    responses: queue.Queue[object] = queue.Queue(maxsize=1)

    def consume() -> None:
        events = sandbox.files.watch(root)
        try:
            responses.put(next(events))
        except Exception as error:
            responses.put(error)

    thread = threading.Thread(target=consume, daemon=True)
    thread.start()
    time.sleep(0.5)
    sandbox.files.write(f"{root}/watch.txt", "watch-ok")
    try:
        event = responses.get(timeout=10)
    except queue.Empty as error:
        raise AssertionError("filesystem watcher did not receive an event") from error
    if isinstance(event, Exception):
        raise event
    _expect(isinstance(event, Mapping), "filesystem watcher returned an invalid event")


def validate_pty(sandbox: Sandbox, validator: Validator) -> None:
    validator.verify("pty.interaction", lambda: _validate_pty(sandbox))


def _validate_pty(sandbox: Sandbox) -> None:
    session = sandbox.pty.start(size=PtySize(rows=24, cols=80))
    sandbox.pty.resize(session.pid, PtySize(rows=30, cols=100))
    pid = session.pid
    session.disconnect()
    session = sandbox.pty.connect(pid)
    session.send_stdin("printf 'pty-ok\\n'; exit\n")
    result = session.wait(check=False)
    _expect(result.exit_code == 0, f"PTY exited with status {result.exit_code}")
    _expect("pty-ok" in result.stdout, "PTY output is missing")


def validate_git(sandbox: Sandbox, validator: Validator) -> None:
    validator.verify("git.workflow", lambda: _validate_git(sandbox))


def _validate_git(sandbox: Sandbox) -> None:
    root = f"/tmp/devbox-sdk-git-{uuid4().hex[:8]}"
    source = f"{root}/source"
    remote = f"{root}/remote.git"
    clone = f"{root}/clone"
    sandbox.commands.run(
        f"mkdir -p {root} && git init --bare {remote} && git init -b main {source}"
    )
    sandbox.git.set_config(source, "user.name", "DevBox SDK")
    sandbox.git.set_config(source, "user.email", "sdk@devbox.local")
    sandbox.files.write(f"{source}/README.md", "first\n")
    sandbox.git.add(source)
    sandbox.git.commit(source, "first")
    sandbox.commands.run(f"git -C {source} remote add origin {remote}")
    sandbox.git.push(source, branch="main")
    sandbox.git.clone(remote, clone, branch="main")
    sandbox.git.checkout(clone, "validation", create=True)
    sandbox.git.status(clone)
    sandbox.files.write(f"{source}/README.md", "second\n")
    sandbox.git.add(source)
    sandbox.git.commit(source, "second")
    sandbox.git.push(source, branch="main")
    sandbox.git.pull(clone, branch="main")
    _expect(sandbox.files.read(f"{clone}/README.md") == "second\n", "git pull did not update")
    sandbox.files.remove(root)


def validate_pause_resume(sandbox: Sandbox) -> None:
    sandbox.pause()
    sandbox.resume(timeout=300)


def _expect_result(
    result: CommandResult,
    *,
    stdout: str | None = None,
    stderr: str | None = None,
) -> None:
    _expect(result.exit_code == 0, f"command exited with status {result.exit_code}")
    if stdout is not None:
        _expect(result.stdout == stdout, f"unexpected stdout: {result.stdout!r}")
    if stderr is not None:
        _expect(result.stderr == stderr, f"unexpected stderr: {result.stderr!r}")


def _expect_id(info: object, sandbox_id: str) -> None:
    _expect(getattr(info, "sandbox_id", None) == sandbox_id, "sandbox ID differs")


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


if __name__ == "__main__":
    try:
        main()
    except DevBoxError as error:
        raise SystemExit(f"Full validation stopped: {error}") from None
