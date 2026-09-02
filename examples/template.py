from devbox import DevBox, Template


def main() -> None:
    definition = Template(
        alias="python-app",
        name="Python application",
        vcpu=2,
        ram_mb=2048,
        start_command="python /opt/app/main.py",
    )

    with DevBox() as client:
        template = client.templates.create(definition)
        print(f"template={template.template_id}")


if __name__ == "__main__":
    main()
