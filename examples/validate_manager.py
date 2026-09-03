from __future__ import annotations

import os
from collections.abc import Callable
from typing import TypeVar

from devbox import DevBox, DevBoxError, NetworkConfig

T = TypeVar("T")


def main() -> None:
    failures: list[str] = []

    def verify(name: str, operation: Callable[[], T]) -> T | None:
        try:
            result = operation()
        except (DevBoxError, ValueError) as error:
            failures.append(name)
            print(f"FAIL {name}: {error}")
            return None
        print(f"PASS {name}")
        return result

    template_id = os.getenv("DEVBOX_TEST_TEMPLATE", "").strip()
    if not template_id:
        failures.append("configuration.template")
        print("FAIL configuration.template: DEVBOX_TEST_TEMPLATE is required")

    with DevBox() as client:
        sandboxes = verify("sandboxes.list", lambda: client.sandboxes.list(limit=20))
        if sandboxes:
            print(f"  sandboxes={len(sandboxes.items)} total_running={sandboxes.total}")

        if template_id:
            validate_sandbox(client, template_id, verify, failures)

    if failures:
        names = ", ".join(failures)
        print(f"Manager validation failed ({len(failures)}): {names}")
        raise SystemExit(1)
    print("Manager validation passed")


def validate_sandbox(
    client: DevBox,
    template_id: str,
    verify: Callable[[str, Callable[[], T]], T | None],
    failures: list[str],
) -> None:
    sandbox = verify(
        "sandboxes.create",
        lambda: client.sandboxes.create(
            template_id,
            timeout=300,
            metadata={"sdk_validation": "true"},
            network=NetworkConfig(allow_internet_access=True),
        ),
    )
    if sandbox is None:
        return

    try:
        verify("sandboxes.get", sandbox.get_info)
        verify("sandboxes.set_timeout", lambda: sandbox.set_timeout(300))
        verify("sandboxes.refresh", lambda: sandbox.refresh(300))
        verify("sandboxes.metrics", sandbox.get_metrics)
        verify(
            "sandboxes.aggregate_metrics",
            lambda: client.sandboxes.metrics([sandbox.sandbox_id]),
        )
        verify("sandboxes.logs", lambda: sandbox.get_logs(limit=20))
        verify(
            "sandboxes.update_network",
            lambda: sandbox.update_network(NetworkConfig(allow_internet_access=True)),
        )
        verify("sandboxes.pause", sandbox.pause)
        verify("sandboxes.connect", lambda: sandbox.resume(timeout=300))
    finally:
        verify("sandboxes.delete", sandbox.kill)
        sandbox.close()


if __name__ == "__main__":
    main()
