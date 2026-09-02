from devbox import Sandbox


def main() -> None:
    with Sandbox.create(timeout=300) as sandbox:
        print(f"sandbox: {sandbox.sandbox_id}")
        result = sandbox.commands.run("python --version")
        print(result.stdout or result.stderr)
        sandbox.kill()


if __name__ == "__main__":
    main()
