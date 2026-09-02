from devbox import DevBox


def main() -> None:
    with DevBox() as client:
        page = client.sandboxes.list()
        print(f"sandboxes: {len(page.items)}")
        for sandbox in page.items:
            print(f"{sandbox.sandbox_id} {sandbox.state.value} {sandbox.template_id}")


if __name__ == "__main__":
    main()
