from devbox import DevBox, Template


def main() -> None:
    definition = (
        Template.from_image("python:3.12-slim")
        .set_env(PYTHONUNBUFFERED="1")
        .add_file("print('ready')\n", "/opt/app/main.py")
        .run("python -m compileall /opt/app")
        .set_start_command("python /opt/app/main.py")
    )

    with DevBox() as client:
        template = client.templates.create(definition, alias="python-app")
        build = client.templates.build(template.template_id)
        print(f"template={template.template_id} build={build.build_id}")


if __name__ == "__main__":
    main()
