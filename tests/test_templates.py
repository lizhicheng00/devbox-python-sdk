from __future__ import annotations

import json

import httpx

from devbox import DevBox, Template


def test_template_builder_is_immutable() -> None:
    base = Template.from_image("python:3.12-slim")
    configured = base.set_env(APP_ENV="test").run("python --version")

    assert base.envs == {}
    assert base.commands == ()
    assert configured.envs == {"APP_ENV": "test"}
    assert configured.commands == ("python --version",)


def test_template_create_uses_declarative_definition() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            201,
            json={
                "templateId": "tpl_123",
                "alias": "python-app",
                "createdAt": "2026-09-02T00:00:00Z",
                "updatedAt": "2026-09-02T00:00:00Z",
            },
        )

    definition = (
        Template.from_image("python:3.12-slim")
        .add_file("print('ready')\n", "/opt/app/main.py")
        .set_start_command("python /opt/app/main.py")
    )
    with DevBox(
        api_key="devbox_secret",
        api_url="https://api.example.test",
        http_transport=httpx.MockTransport(handler),
    ) as client:
        template = client.templates.create(definition, alias="python-app")

    body = json.loads(captured[0].content)
    assert body["definition"]["image"] == "python:3.12-slim"
    assert body["definition"]["files"][0]["encoding"] == "base64"
    assert captured[0].headers["Idempotency-Key"]
    assert template.template_id == "tpl_123"
