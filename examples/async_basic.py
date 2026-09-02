import asyncio

from devbox import AsyncSandbox


async def main() -> None:
    async with await AsyncSandbox.create(timeout=300) as sandbox:
        print(f"sandbox: {sandbox.sandbox_id}")
        result = await sandbox.commands.run("python --version")
        print(result.stdout or result.stderr)
        await sandbox.kill()


if __name__ == "__main__":
    asyncio.run(main())
