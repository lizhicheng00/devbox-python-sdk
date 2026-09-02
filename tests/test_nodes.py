from __future__ import annotations

import httpx

from devbox import DevBox, NodeStatus


def test_health_and_nodes() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            assert "X-API-Key" in request.headers
            return httpx.Response(200, json={"status": "ok"})
        if request.method == "POST":
            return httpx.Response(200, json={"node_id": "node_1", "status": "draining"})
        return httpx.Response(200, json={"nodes": [{"node_id": "node_1", "status": "ready"}]})

    with DevBox(
        api_key="secret", api_url="https://api.test", http_transport=httpx.MockTransport(handler)
    ) as api:
        health = api.health()
        nodes = api.nodes.list()
        updated = api.nodes.update_status("node_1", NodeStatus.DRAINING)

    assert health.status == "ok"
    assert nodes[0].node_id == "node_1"
    assert updated.status == "draining"
