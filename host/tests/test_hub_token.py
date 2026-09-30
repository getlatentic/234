# SPDX-License-Identifier: AGPL-3.0-or-later
"""The host presents the connectors' bearer token on every MCP request, and only when it has one."""

import httpx

from turns.hub import Hub, build_hub
from turns.settings import Settings


def recording_client(seen: list[httpx.Request]) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {"tools": []}})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_every_request_to_a_connector_carries_the_token():
    seen: list[httpx.Request] = []
    hub = Hub({"s": "http://s/mcp"}, recording_client(seen), "secret-token")
    await hub.tools("s")
    assert len(seen) >= 2
    assert {r.headers["authorization"] for r in seen} == {"Bearer secret-token"}


async def test_without_a_token_no_authorization_header_is_sent():
    seen: list[httpx.Request] = []
    await Hub({"s": "http://s/mcp"}, recording_client(seen)).tools("s")
    assert all("authorization" not in r.headers for r in seen)


async def test_build_hub_gives_the_token_to_every_connector():
    seen: list[httpx.Request] = []
    hub = build_hub("https://c.example", ("a", "b"), recording_client(seen), "tok")
    await hub.tools("a")
    await hub.tools("b")
    assert {str(r.url) for r in seen} == {"https://c.example/a/mcp", "https://c.example/b/mcp"}
    assert {r.headers["authorization"] for r in seen} == {"Bearer tok"}


def test_settings_read_the_token_from_the_worker_secret():
    assert Settings.from_env({"CHECKOUT_MCP_TOKEN": "tok"}.get).mcp_token == "tok"
    assert Settings.from_env({}.get).mcp_token == ""
