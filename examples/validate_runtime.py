from __future__ import annotations

import os
import sys
from collections.abc import Mapping

from devbox import CommandHandle, CommandResult, DevBoxError, Sandbox


def main() -> None:
    sandbox_id = os.getenv("DEVBOX_SANDBOX_ID", "").strip()
    created = not sandbox_id
    template = os.getenv("DEVBOX_TEST_TEMPLATE", "default")

    try:
        sandbox = (
            Sandbox.connect(sandbox_id, timeout=300)
            if sandbox_id
            else Sandbox.create(
                template,
                timeout=300,
                metadata={"sdk_validation": "true"},
            )
        )
    except DevBoxError as error:
        raise SystemExit(f"Unable to open sandbox: {error}") from None

    print(f"Sandbox ready: {sandbox.sandbox_id}")
    try:
        validate_commands(sandbox)
        validate_filesystem(sandbox)
        print("Sandbox runtime validation passed")
    except (DevBoxError, AssertionError, ValueError) as error:
        raise SystemExit(f"Sandbox runtime validation failed: {error}") from None
    finally:
        if created:
            try:
                sandbox.kill()
                print(f"Deleted test sandbox: {sandbox.sandbox_id}")
            except DevBoxError as error:
                print(f"Failed to delete test sandbox: {error}", file=sys.stderr)
        sandbox.close()


def validate_commands(sandbox: Sandbox) -> None:
    run(sandbox, "working directory", "pwd")
    run(sandbox, "system information", "uname -a")
    run(sandbox, "Python runtime", "python3 --version || python --version")
    run(
        sandbox,
        "environment",
        'printf "$DEVBOX_SDK_TEST"',
        envs={"DEVBOX_SDK_TEST": "env-ok"},
        expected_stdout="env-ok",
    )
    run(sandbox, "working directory option", "pwd", cwd="/tmp", expected_stdout="/tmp\n")
    run(
        sandbox,
        "stderr and exit code",
        "printf 'stderr-ok\\n' >&2; exit 7",
        expected_stderr="stderr-ok\n",
        expected_exit=7,
    )

    print("\n== background process ==")
    handle = sandbox.commands.run("sleep 1; printf background-ok", background=True)
    if not isinstance(handle, CommandHandle):
        raise AssertionError("background command did not return a process handle")
    print(f"pid={handle.pid}")
    processes = sandbox.commands.list()
    if handle.pid not in {process.pid for process in processes}:
        raise AssertionError("background process is missing from process list")
    result = handle.wait(check=False)
    print_result(result)
    if result.exit_code != 0 or result.stdout != "background-ok":
        raise AssertionError("background command returned an unexpected result")


def validate_filesystem(sandbox: Sandbox) -> None:
    print("\n== filesystem ==")
    directory = "/tmp/devbox-sdk-validation"
    path = f"{directory}/message.txt"
    sandbox.files.make_dir(directory)
    info = sandbox.files.write(path, "filesystem-ok")
    print(f"write: {info.path} size={info.size}")
    content = sandbox.files.read(path)
    print(f"read: {content}")
    if content != "filesystem-ok":
        raise AssertionError("filesystem content does not match")
    print(f"stat: {sandbox.files.stat(path)}")
    print(f"list: {sandbox.files.list(directory)}")
    sandbox.files.remove(directory, recursive=True)
    print("remove: ok")


def run(
    sandbox: Sandbox,
    name: str,
    command: str,
    *,
    envs: Mapping[str, str] | None = None,
    cwd: str | None = None,
    expected_stdout: str | None = None,
    expected_stderr: str | None = None,
    expected_exit: int = 0,
) -> None:
    print(f"\n== {name} ==")
    print(f"$ {command}")
    result = sandbox.commands.run(
        command,
        envs=envs,
        cwd=cwd,
        on_stdout=lambda value: print(value, end="", flush=True),
        on_stderr=lambda value: print(value, end="", file=sys.stderr, flush=True),
        check=False,
    )
    if not isinstance(result, CommandResult):
        raise AssertionError("foreground command returned a process handle")
    print_result(result)
    if result.exit_code != expected_exit:
        raise AssertionError(f"expected exit {expected_exit}, got {result.exit_code}")
    if expected_stdout is not None and result.stdout != expected_stdout:
        raise AssertionError(f"unexpected stdout: {result.stdout!r}")
    if expected_stderr is not None and result.stderr != expected_stderr:
        raise AssertionError(f"unexpected stderr: {result.stderr!r}")


def print_result(result: CommandResult) -> None:
    print(f"\n[exit={result.exit_code} pid={result.pid}]")


if __name__ == "__main__":
    main()
