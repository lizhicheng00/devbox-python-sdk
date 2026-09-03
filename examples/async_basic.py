import asyncio
import os

from devbox import AsyncSandbox


async def main() -> None:
    template = os.getenv("DEVBOX_TEST_TEMPLATE", "default")
    async with await AsyncSandbox.create(template, timeout=300) as sandbox:
        print(f"sandbox: {sandbox.sandbox_id}")
        result = await sandbox.commands.run("python --version")
        print(result.stdout or result.stderr, end="")


if __name__ == "__main__":
    asyncio.run(main())
