# DevBox Python SDK

Python client for creating and operating isolated DevBox sandboxes.

The SDK keeps the public API small while covering the first-phase workflow:

- create, connect, inspect, pause, resume, fork, snapshot, and delete sandboxes;
- run foreground or background commands and reconnect to running processes;
- read, write, upload, download, inspect, and watch files;
- open interactive PTY sessions;
- run common Git workflows without putting credentials in command arguments;
- manage templates, builds, snapshots, and compute nodes;
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

Team snapshots can be paged independently with `client.snapshots.list()`.

## Async API

The asynchronous client mirrors the synchronous API:

```python
import asyncio

from devbox import AsyncSandbox


async def main() -> None:
    async with await AsyncSandbox.create("python") as sandbox:
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

Run the same smoke validation used by the PyCharm `DevBox Basic` configuration:

```bash
python examples/validate_manager.py
```

Set `DEVBOX_TEST_TEMPLATE` to a deployed template ID. The validator is strict:
missing Manager endpoints, missing configuration, lifecycle failures, unavailable
envd command routing, or unexpected command output produce a non-zero exit code.

Command, filesystem, PTY, and Git operations require the Manager to return a real
envd domain and access token. Placeholder connection fields are accepted when only
control-plane lifecycle operations are used.

## Interactive Console

Run `examples/interactive_console.py` from PyCharm for a zero-input runtime check.
It creates a sandbox from `DEVBOX_TEST_TEMPLATE` (default: `default`), validates
foreground and background commands, process listing, and filesystem operations,
then deletes the test sandbox. Set `DEVBOX_SANDBOX_ID` only when an existing sandbox
should be reused instead.

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
