# DevBox Python SDK

Python client for creating and operating isolated DevBox sandboxes.

The SDK keeps the public API small while covering sandbox lifecycle and runtime work:

- create, connect, inspect, pause, resume, fork, snapshot, and delete sandboxes;
- run foreground or background commands and reconnect to running processes;
- read, write, upload, download, inspect, and watch files;
- open interactive PTY sessions;
- run common Git workflows without putting credentials in command arguments;
- call template, build, snapshot, and compute-node resources when exposed by the Manager;
- use the same capabilities from synchronous or asynchronous applications.

## Install

```bash
pip install devbox-sdk
```

Python 3.10 or newer is required.

## Quick Start

Set the API key issued by the DevBox management service:

```bash
export DEVBOX_API_KEY=devbox_xxx
```

Create a sandbox and run a command:

```python
from devbox import Sandbox

with Sandbox.create("python", timeout=300) as sandbox:
    result = sandbox.commands.run("python --version")
    print(result.stdout, end="")

    sandbox.files.write("/tmp/message.txt", "hello from DevBox\n")
    print(sandbox.files.read("/tmp/message.txt"), end="")
```

The context manager deletes the remote sandbox and closes local HTTP resources on
exit. Without a context manager, call `kill()` to delete the sandbox or `close()`
to release only local resources and leave the sandbox running until its timeout.

## Reusable Client

Use `DevBox` when an application creates or queries multiple sandboxes:

```python
from devbox import DevBox, NetworkConfig

with DevBox() as client:
    sandbox = client.sandboxes.create(
        template="python",
        timeout=600,
        envs={"APP_ENV": "test"},
        metadata={"job": "example"},
        network=NetworkConfig(
            allow_internet_access=True,
            allow_public_traffic=False,
        ),
    )
    print(sandbox.sandbox_id)

    # Reset the inactivity timeout after useful work.
    sandbox.refresh()
```

Team snapshots can be paged independently with `client.snapshots.list()`.

## Async API

The asynchronous client mirrors the synchronous API:

```python
import asyncio

from devbox import AsyncSandbox


async def main() -> None:
    async with await AsyncSandbox.create("python") as sandbox:
        result = await sandbox.commands.run("uname -a")
        print(result.stdout, end="")


asyncio.run(main())
```

## Commands

Foreground commands return `CommandResult`. Output callbacks receive chunks while
the command runs:

```python
result = sandbox.commands.run(
    "python -u worker.py",
    on_stdout=lambda chunk: print(chunk, end=""),
    on_stderr=lambda chunk: print(chunk, end=""),
)
```

Start a background command when its lifetime should outlive the current request:

```python
handle = sandbox.commands.run("python server.py", background=True, timeout=300)
print(handle.pid)

handle.send_stdin("input\n")
result = handle.wait()
```

`timeout` bounds the command stream. Use `None` or `0` for a stream without a
client deadline. Background output callbacks are supplied to `handle.wait()`.

Non-zero foreground exits raise `CommandExitError` by default. Pass `check=False`
to inspect the result without raising.

## Files

```python
sandbox.files.write_batch(
    {
        "/workspace/app.py": "print('ready')\n",
        "/workspace/config.json": b"{}",
    }
)

entries = sandbox.files.list("/workspace")
exists = sandbox.files.exists("/workspace/app.py")
sandbox.files.upload("./input.csv", "/workspace/input.csv")
sandbox.files.download("/workspace/output.csv", "./output.csv")
```

Sandbox paths must be absolute. Binary content is transferred without text
conversion.

## PTY

```python
from devbox import PtySize

session = sandbox.pty.start("/bin/bash", size=PtySize(rows=30, cols=100))
session.send_stdin("ls -la\n")
sandbox.pty.resize(session.pid, PtySize(rows=40, cols=120))
session.disconnect()

session = sandbox.pty.connect(session.pid)
session.send_stdin("exit\n")
session.wait(on_stdout=lambda data: print(data, end=""), check=False)
```

The returned process ID can be stored and used to reconnect while the sandbox and
process remain alive.

## Git

```python
import os

from devbox import GitCredentials

credentials = GitCredentials(username="user", password=os.environ["GIT_TOKEN"])
sandbox.git.clone(
    "https://example.com/team/project.git",
    "/workspace/project",
    credentials=credentials,
)
sandbox.git.checkout("/workspace/project", "feature", create=True)
```

Credentials are passed as process environment values to Git's credential helper.
They are not embedded in repository URLs or shell command arguments.

## Templates

Templates use the Manager service's template and build resources:

```python
from devbox import DevBox, Template

definition = Template(
    alias="python-app",
    name="Python application",
    vcpu=2,
    ram_mb=2048,
    start_command="python /opt/app/main.py",
)

with DevBox() as client:
    template = client.templates.create(definition)
    build = client.templates.start_build(template.template_id, "build-id")
    print(client.templates.get_build_logs(template.template_id, build.build_id))
```

## Manager Validation

Run the control-plane smoke validation used by the PyCharm `DevBox Manager` configuration:

```bash
python examples/validate_manager.py
```

Set `DEVBOX_TEST_TEMPLATE` to a deployed template ID. The validator covers only the
phase-one `/sandboxes` surface. Configuration or lifecycle failures produce a non-zero
exit code; Manager resources that are not published in this deployment are not probed.

Command, filesystem, PTY, and Git operations use EnvD's ConnectRPC and `/files`
protocols. The Manager supplies the short-lived access token. Deployments with a
shared data-plane ingress can set `DEVBOX_GATEWAY_URL` instead of returning a
per-sandbox gateway address.

## Runtime Validation

Run `examples/validate_runtime.py` from PyCharm for a zero-input runtime check.
It creates a sandbox from `DEVBOX_TEST_TEMPLATE` (default: `default`), validates
foreground and background commands, process listing, and filesystem operations,
then deletes the test sandbox. Set `DEVBOX_SANDBOX_ID` only when an existing sandbox
should be reused instead.

## Full Validation

Run `examples/validate_full.py` for a zero-input phase-one acceptance check. It
creates one temporary sandbox and validates the published Manager lifecycle plus
commands, process interaction and reconnection, filesystem transfer and watching,
PTY, and a local Git workflow. It reports a single runtime gateway failure instead
of cascading data-plane errors, and deletes the sandbox even when a check fails.

## Errors

HTTP failures are mapped to typed exceptions:

- `AuthenticationError` and `PermissionDeniedError` for authentication failures;
- `ValidationError`, `NotFoundError`, and `ConflictError` for request errors;
- `RateLimitError` for throttling, including `retry_after` when provided;
- `RequestTimeoutError` and `ServiceUnavailableError` for transient failures;
- `ProtocolError` when a successful response violates the service contract.

All exceptions inherit from `DevBoxError` and expose `code`, `status_code`,
`request_id`, `target`, and structured `details` when returned by the service.

## Configuration

| Setting | Environment variable | Default |
| --- | --- | --- |
| API key | `DEVBOX_API_KEY` or `E2B_API_KEY` | required |
| Control-plane URL | `DEVBOX_API_URL` or `E2B_API_URL` | `https://devbox.developer.myhuaweicloud.com` |
| Data-plane URL override | `DEVBOX_GATEWAY_URL` | Manager response |
| Request timeout | constructor argument | 30 seconds |

Constructor arguments take precedence over `DEVBOX_*`, followed by E2B-compatible
environment variables.

The API key is sent only to the control plane as `X-API-Key`. Create and connect
responses provide a short-lived sandbox connection token; only that token is sent
to the gateway. The SDK does not persist either credential.

The SDK retries connection-establishment failures twice. It does not automatically
retry rate limits, server errors, or requests that may already have reached the
service. `RateLimitError.retry_after` exposes the server's retry guidance.

## Development

```bash
python -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy
.venv/bin/pytest
.venv/bin/python -m build
```

The public package is hand-maintained. HTTP and streaming protocol details stay in
internal modules so generated OpenAPI or Connect clients can replace them without
changing user-facing objects.
