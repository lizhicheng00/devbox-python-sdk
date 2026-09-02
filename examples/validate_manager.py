from __future__ import annotations

import os
from collections.abc import Callable
from typing import TypeVar

from devbox import DevBox, DevBoxError, NetworkConfig, NotFoundError

T = TypeVar("T")


def check(
    name: str, operation: Callable[[], T], *, optional: bool, strict: bool
) -> tuple[bool, T | None]:
    try:
        result = operation()
    except NotFoundError:
        if optional and not strict:
            print(f"SKIP {name}: endpoint is not available in this deployment")
            return True, None
        print(f"FAIL {name}: endpoint was not found")
        return False, None
    except DevBoxError as error:
        print(f"FAIL {name}: HTTP {error.status_code or '-'} {error}")
        return False, None
    print(f"PASS {name}")
    return True, result


def main() -> None:
    failures = 0
    strict = os.getenv("DEVBOX_STRICT_VALIDATION") == "1"

    def verify(name: str, operation: Callable[[], T], *, optional: bool = False) -> T | None:
        nonlocal failures
        passed, result = check(name, operation, optional=optional, strict=strict)
        if not passed:
            failures += 1
        return result

    with DevBox() as client:
        health = verify("health", client.health, optional=True)
        sandboxes = verify("sandboxes.list", lambda: client.sandboxes.list(limit=20))
        snapshots = verify("snapshots.list", lambda: client.snapshots.list(limit=20), optional=True)
        templates = verify("templates.list", client.templates.list, optional=True)
        nodes = verify("nodes.list", client.nodes.list, optional=True)

        if health:
            print(f"  status={health.status}")
        if sandboxes:
            print(f"  sandboxes={len(sandboxes.items)} total_running={sandboxes.total}")
        if snapshots:
            print(f"  snapshots={len(snapshots.items)}")
        if templates is not None:
            print(f"  templates={len(templates)}")
        if nodes is not None:
            print(f"  nodes={len(nodes)}")

        template_id = os.getenv("DEVBOX_TEST_TEMPLATE")
        if not template_id:
            print("SKIP sandbox lifecycle: DEVBOX_TEST_TEMPLATE is not configured")
        else:
            sandbox = verify(
                "sandboxes.create",
                lambda: client.sandboxes.create(
                    template_id,
                    timeout=300,
                    metadata={"sdk_validation": "true"},
                    network=NetworkConfig(allow_internet_access=True),
                ),
            )
            if sandbox:
                try:
                    verify("sandboxes.get", sandbox.get_info)
                    verify("sandboxes.set_timeout", lambda: sandbox.set_timeout(300))
                    verify("sandboxes.refresh", lambda: sandbox.refresh(300))
                    verify("sandboxes.metrics", sandbox.get_metrics)
                    verify("sandboxes.logs", lambda: sandbox.get_logs(limit=20))
                    verify(
                        "sandboxes.update_network",
                        lambda: sandbox.update_network(NetworkConfig(allow_internet_access=True)),
                    )
                    verify("sandboxes.pause", sandbox.pause)
                    verify("sandboxes.connect", lambda: sandbox.resume(timeout=300))
                finally:
                    verify("sandboxes.delete", sandbox.kill)

    if failures:
        raise SystemExit(f"Manager validation failed: {failures} check(s)")
    print("Manager validation passed")


if __name__ == "__main__":
    main()
