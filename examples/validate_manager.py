from __future__ import annotations

import os
from collections.abc import Callable
from typing import TypeVar

from devbox import DevBox, DevBoxError, NetworkConfig

T = TypeVar("T")


class Validator:
    def __init__(self) -> None:
        self.failures: list[str] = []

    def verify(self, name: str, operation: Callable[[], T]) -> T | None:
        try:
            result = operation()
        except (DevBoxError, ValueError) as error:
            self.failures.append(name)
            print(f"FAIL {name}: {error}")
            return None
        print(f"PASS {name}")
        return result


def main() -> None:
    validator = Validator()

    template_id = os.getenv("DEVBOX_TEST_TEMPLATE", "").strip()
    if not template_id:
        validator.failures.append("configuration.template")
        print("FAIL configuration.template: DEVBOX_TEST_TEMPLATE is required")

    with DevBox() as client:
        sandboxes = validator.verify("sandboxes.list", lambda: client.sandboxes.list(limit=20))
        if sandboxes:
            print(f"  sandboxes={len(sandboxes.items)} total_running={sandboxes.total}")

        if template_id:
            validate_sandbox(client, template_id, validator)

    if validator.failures:
        names = ", ".join(validator.failures)
        print(f"Manager validation failed ({len(validator.failures)}): {names}")
        raise SystemExit(1)
    print("Manager validation passed")


def validate_sandbox(
    client: DevBox,
    template_id: str,
    validator: Validator,
) -> None:
    sandbox = validator.verify(
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
        validator.verify("sandboxes.get", sandbox.get_info)
        validator.verify("sandboxes.set_timeout", lambda: sandbox.set_timeout(300))
        validator.verify("sandboxes.refresh", lambda: sandbox.refresh(300))
        validator.verify("sandboxes.metrics", sandbox.get_metrics)
        validator.verify(
            "sandboxes.aggregate_metrics",
            lambda: client.sandboxes.metrics([sandbox.sandbox_id]),
        )
        validator.verify("sandboxes.logs", lambda: sandbox.get_logs(limit=20))
        validator.verify(
            "sandboxes.update_network",
            lambda: sandbox.update_network(NetworkConfig(allow_internet_access=True)),
        )
        validator.verify("sandboxes.pause", sandbox.pause)
        validator.verify("sandboxes.connect", lambda: sandbox.resume(timeout=300))
    finally:
        validator.verify("sandboxes.delete", sandbox.kill)
        sandbox.close()


if __name__ == "__main__":
    main()
