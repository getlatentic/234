# SPDX-License-Identifier: AGPL-3.0-or-later
"""The memory connector is told the owner of the notes in a header of its own; another connector is told it
only for an account's call (tests/test_wallet.py)."""

import json

import httpx
import pytest

from turns.hub import MEMORY_OWNER_HEADER, OWNER_HEADER, Hub

OWNER = "ab" * 16
SEEN: list[httpx.Request] = []
TOOL = {"name": "memory_index", "inputSchema": {"type": "object"}, "_meta": {"ui": {"visibility": ["app"]}}}
MODEL = {"name": "recall", "inputSchema": {"type": "object"}, "_meta": {"ui": {"visibility": ["model"]}}}
OTHER = {"name": "make", "inputSchema": {"type": "object"}}


def handler(request: httpx.Request) -> httpx.Response:
    SEEN.append(request)
    body = json.loads(request.content)
    result = {
        "tools/list": {"tools": [TOOL, MODEL, OTHER]},
        "tools/call": {"content": [{"type": "text", "text": "ok"}]},
    }.get(body.get("method"), {})
    return httpx.Response(200, json={"jsonrpc": "2.0", "id": body.get("id"), "result": result})


@pytest.fixture
def hub():
    SEEN.clear()
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return Hub({"memory": "http://m/mcp", "s": "http://s/mcp"}, client)


def called() -> list[httpx.Request]:
    return [r for r in SEEN if json.loads(r.content).get("method") == "tools/call"]


async def test_a_call_to_the_memory_connector_carries_both_owner_headers(hub):
    await hub.call_app_tool("memory", "memory_index", {}, OWNER)
    await hub.call_model_tool("memory__recall", {"query": "x"}, OWNER, "k" * 40)
    sent = called()
    assert len(sent) == 2
    assert [(r.headers[OWNER_HEADER], r.headers[MEMORY_OWNER_HEADER]) for r in sent] == [(OWNER, OWNER)] * 2


async def test_a_call_to_any_other_connector_carries_the_ledger_owner_only(hub):
    await hub.call_model_tool("s__make", {}, OWNER, "k" * 40)
    [request] = called()
    assert request.headers[OWNER_HEADER] == OWNER and MEMORY_OWNER_HEADER not in request.headers


async def test_what_is_not_a_tool_call_carries_neither_header(hub):
    await hub.tools("memory")
    assert SEEN and all(MEMORY_OWNER_HEADER not in r.headers and OWNER_HEADER not in r.headers for r in SEEN)


async def test_what_a_caller_puts_in_the_arguments_never_becomes_the_memory_owner(hub):
    sly = {"_meta": {"memory_owner": "ff" * 16}, MEMORY_OWNER_HEADER: "ff" * 16, "id": "0" * 16}
    await hub.call_app_tool("memory", "memory_index", sly, OWNER)
    [request] = called()
    assert request.headers[MEMORY_OWNER_HEADER] == OWNER
    assert json.loads(request.content)["params"]["arguments"] == sly
