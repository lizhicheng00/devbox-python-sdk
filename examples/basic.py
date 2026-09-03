import os

from devbox import Sandbox


def main() -> None:
    template = os.getenv("DEVBOX_TEST_TEMPLATE", "default")
    with Sandbox.create(template, timeout=300) as sandbox:
        print(f"sandbox: {sandbox.sandbox_id}")
        result = sandbox.commands.run("python --version")
        print(result.stdout or result.stderr, end="")


if __name__ == "__main__":
    main()
