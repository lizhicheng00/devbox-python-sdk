from __future__ import annotations

import os
import sys

from devbox import CommandExitError, DevBoxError, ProtocolError, Sandbox


def main() -> None:
    sandbox_id = (
        os.getenv("DEVBOX_SANDBOX_ID")
        or input("Existing sandbox ID (Enter to create one): ").strip()
    )
    created = not sandbox_id
    try:
        sandbox = connect(sandbox_id) if sandbox_id else create()
    except DevBoxError as error:
        raise SystemExit(f"Unable to open sandbox: {error}") from None
    keep = not created

    print(f"Connected to sandbox {sandbox.sandbox_id}")
    print("Enter a Linux command, or :help for console commands.")
    try:
        while True:
            command = input("devbox> ").strip()
            if not command:
                continue
            if command == ":help":
                show_help()
            elif command == ":info":
                print(sandbox.get_info())
            elif command == ":processes":
                for process in sandbox.commands.list():
                    print(process)
            elif command.startswith(":timeout "):
                sandbox.set_timeout(int(command.split(maxsplit=1)[1]))
                print("Timeout updated")
            elif command.startswith(":refresh "):
                sandbox.refresh(int(command.split(maxsplit=1)[1]))
                print("Sandbox refreshed")
            elif command == ":pause":
                sandbox.pause()
                print("Sandbox paused")
            elif command == ":resume":
                sandbox.resume()
                print("Sandbox resumed")
            elif command == ":detach":
                keep = True
                break
            elif command == ":kill":
                sandbox.kill()
                keep = True
                print("Sandbox deleted")
                break
            elif command in {":exit", ":quit"}:
                break
            else:
                run(sandbox, command)
    except (EOFError, KeyboardInterrupt):
        print()
    finally:
        if not keep:
            sandbox.kill()
            print(f"Deleted test sandbox {sandbox.sandbox_id}")
        sandbox.close()


def create() -> Sandbox:
    template = os.getenv("DEVBOX_TEST_TEMPLATE") or input("Template ID: ").strip()
    if not template:
        raise SystemExit("A template ID is required to create a sandbox")
    return Sandbox.create(template, timeout=300, metadata={"sdk_console": "true"})


def connect(sandbox_id: str) -> Sandbox:
    return Sandbox.connect(sandbox_id, timeout=300)


def run(sandbox: Sandbox, command: str) -> None:
    try:
        result = sandbox.commands.run(
            command,
            on_stdout=lambda value: print(value, end="", flush=True),
            on_stderr=lambda value: print(value, end="", file=sys.stderr, flush=True),
            check=False,
        )
        print(f"[exit {result.exit_code}]")
    except ProtocolError as error:
        print(f"Command channel unavailable: {error}")
    except (CommandExitError, DevBoxError) as error:
        print(f"Command failed: {error}")


def show_help() -> None:
    print(
        "\n".join(
            (
                ":info             Show sandbox details",
                ":processes        List running processes",
                ":timeout <sec>    Reset sandbox timeout",
                ":refresh <sec>    Extend sandbox lifetime",
                ":pause / :resume  Change sandbox state",
                ":detach           Exit and keep the sandbox",
                ":kill             Delete the sandbox and exit",
                ":exit             Exit; a sandbox created here is deleted",
            )
        )
    )


if __name__ == "__main__":
    main()
