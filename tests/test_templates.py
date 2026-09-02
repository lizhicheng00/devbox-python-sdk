from __future__ import annotations

import json

import httpx

from devbox import DevBox, Template


def test_template_create_and_build_paths_match_manager() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/templates":
            return httpx.Response(202, json={"template_id": "tpl_1", "namespace": "ns_1"})
        return httpx.Response(202, json={"template_id": "tpl_1", "build_id": "build_1"})

    with DevBox(
        api_key="secret", api_url="https://api.test", http_transport=httpx.MockTransport(handler)
    ) as api:
        template = api.templates.create(
            Template(
                alias="python",
                name="Python",
                vcpu=2,
                ram_mb=2048,
                start_command="python /app/main.py",
            )
        )
        build = api.templates.start_build(template.template_id, "build_1")

    assert json.loads(requests[0].content)["start_command"] == "python /app/main.py"
    assert requests[1].url.path == "/v2/templates/tpl_1/builds/build_1"
    assert build.build_id == "build_1"


def test_template_query_update_and_tags() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/templates":
            return httpx.Response(
                200, json={"templates": [{"template_id": "tpl_1", "namespace": "ns_1"}]}
            )
        if request.url.path.endswith("/tags"):
            return httpx.Response(200, json={"tags": ["latest"]})
        return httpx.Response(204)

    with DevBox(
        api_key="secret", api_url="https://api.test", http_transport=httpx.MockTransport(handler)
    ) as api:
        templates = api.templates.list()
        api.templates.update("tpl_1", name="Python 3")
        tags = api.templates.list_tags("tpl_1")

    assert templates[0].template_id == "tpl_1"
    assert tags == ("latest",)
    assert paths == ["/templates", "/templates/tpl_1", "/templates/tpl_1/tags"]
