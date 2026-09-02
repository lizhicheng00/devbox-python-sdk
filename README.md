# DevBox Python SDK

Python client for creating and operating isolated DevBox sandboxes.

The SDK keeps the public API small while covering the first-phase workflow:

- create, connect, inspect, pause, resume, fork, snapshot, and delete sandboxes;
- run foreground or background commands and reconnect to running processes;
- read, write, upload, download, inspect, and watch files;
- open interactive PTY sessions;
- run common Git workflows without putting credentials in command arguments;
- create and build declarative templates;
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

with Sandbox.create(timeout=300) as sandbox:
    result = sandbox.commands.run("python --version")
    print(result.stdout)

    sandbox.files.write("/tmp/message.txt", "hello from DevBox\n")
    print(sandbox.files.read("/tmp/message.txt"))

    sandbox.kill()
```

`close()` and context-manager exit release local HTTP resources. They do not delete
the remote sandbox. Use `kill()` when the sandbox should be deleted immediately;
otherwise its configured timeout applies.

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

Create and connect are idempotency-aware. The SDK generates an idempotency key for
each call unless one is supplied explicitly.

Team snapshots can be paged independently with `client.snapshots.list()`.

## Async API

The asynchronous client mirrors the synchronous API:

```python
import asyncio

from devbox import AsyncSandbox


async def main() -> None:
    async with await AsyncSandbox.create() as sandbox:
        result = await sandbox.commands.run("uname -a")
        print(result.stdout)
        await sandbox.kill()


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
handle = sandbox.commands.run("python server.py", background=True)
print(handle.pid)

handle.send_stdin("input\n")
result = handle.wait(timeout=60)
```

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
sandbox.pty.connect(session.pid, on_data=lambda data: print(data, end=""))
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

Template definitions are immutable, so a reusable base definition is not changed by
later additions:

```python
from devbox import DevBox, Template

definition = (
    Template.from_image("python:3.12-slim")
    .set_env(PYTHONUNBUFFERED="1")
    .add_file("print('ready')\n", "/opt/app/main.py")
    .run("python -m compileall /opt/app")
    .set_start_command("python /opt/app/main.py")
)

with DevBox() as client:
    template = client.templates.create(definition, alias="python-app")
    build = client.templates.build(template.template_id)
    for event in client.templates.get_build_logs(template.template_id, build.build_id):
        print(event)
```

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
| Request timeout | constructor argument | 30 seconds |

Constructor arguments take precedence over `DEVBOX_*`, followed by E2B-compatible
environment variables.

The API key is sent only to the control plane as `X-API-Key`. Create and connect
responses provide a short-lived sandbox connection token; only that token is sent
to the gateway. The SDK does not persist either credential.

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
