# SPDX-License-Identifier: AGPL-3.0-or-later
import base64
import json

import httpx
import pytest

from turns.hub import CardPage, Hub, HubError, ToolOutcome

TOOLS = [
    {"name": "create_quote", "description": "d", "inputSchema": {"type": "object", "$schema": "x"},
     "_meta": {"ui": {"resourceUri": "ui://s/card.html", "visibility": ["model"]}}},
    {"name": "approve_quote", "description": "d", "inputSchema": {"type": "object"},
     "_meta": {"ui": {"resourceUri": "ui://s/card.html", "visibility": ["app"]}}},
    {"name": "get_status", "description": "d", "inputSchema": {"type": "object"}},
]  # fmt: skip
CALLS: list[dict] = []
HEADERS: list[dict] = []
OWNER = "ab" * 16
KEY = "k" * 40
MENU_META = {"ui": {"prefersBorder": False, "csp": {"resourceDomains": ["https://cdn.example.com", 7]}}}
LISTED_META = {"ui": {"prefersBorder": True, "csp": {"frameDomains": ["https://checkout.example.com"]}}}
CONTENT_META = {"ui": {"prefersBorder": False}}
MIME = "text/html;profile=mcp-app"


def handler(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    CALLS.append(body)
    HEADERS.append(dict(request.headers))
    method = body.get("method")
    if method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        result = {"content": [{"type": "text", "text": "ok"}]}
    elif method == "resources/list":
        result = {
            "resources": [
                {"uri": "ui://s/card.html"},
                {"uri": "ui://s/menu.html"},
                {"uri": "ui://s/listed.html", "_meta": LISTED_META},
                {"uri": "ui://s/blob.html"},
                {"uri": "ui://s/both.html", "_meta": LISTED_META},
                {"uri": "ui://s/plain.html"},
                {"uri": "file:///secret"},
            ]
        }
    elif method == "resources/read":
        uri = body["params"]["uri"]
        meta = MENU_META if uri.endswith("menu.html") else {}
        content = {"uri": uri, "mimeType": MIME, "text": "<html>", "_meta": meta}
        if uri.endswith("both.html"):
            content["_meta"] = CONTENT_META
        if uri.endswith("blob.html"):
            content = {"uri": uri, "mimeType": MIME, "blob": base64.b64encode(b"<html>blob").decode()}
        if uri.endswith("plain.html"):
            content = {"uri": uri, "mimeType": "text/html", "text": "<html>"}
        result = {"contents": [content]}
    else:
        return httpx.Response(202)
    return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})


@pytest.fixture
def hub():
    CALLS.clear()
    HEADERS.clear()
    return Hub({"s": "http://s/mcp"}, httpx.AsyncClient(transport=httpx.MockTransport(handler)))


async def test_the_model_is_offered_model_visible_tools_only_named_by_connector(hub):
    offered = await hub.model_tools()
    assert [t["function"]["name"] for t in offered] == ["s__create_quote", "s__get_status"]
    assert "$schema" not in offered[0]["function"]["parameters"]


async def test_the_model_cannot_call_an_app_only_tool(hub):
    outcome = await hub.call_model_tool("s__approve_quote", {}, OWNER, KEY)
    assert outcome.is_error and "not available to the model" in outcome.text
    assert not [c for c in CALLS if c.get("method") == "tools/call"]


async def test_the_model_is_told_when_a_tool_does_not_exist(hub):
    outcome = await hub.call_model_tool("s__nope", {}, OWNER, KEY)
    assert outcome.is_error and "no tool" in outcome.text


async def test_a_model_call_returns_the_result_and_the_card_it_names(hub):
    outcome = await hub.call_model_tool("s__create_quote", {"a": 1}, OWNER, KEY)
    assert isinstance(outcome, ToolOutcome)
    assert (outcome.text, outcome.card_uri) == ("ok", "ui://s/card.html")


async def test_a_card_cannot_call_a_model_only_tool_or_an_unknown_one(hub):
    with pytest.raises(HubError, match="not available to cards"):
        await hub.call_app_tool("s", "create_quote", {}, OWNER)
    with pytest.raises(HubError, match="no tool"):
        await hub.call_app_tool("s", "nope", {}, OWNER)
    assert (await hub.call_app_tool("s", "approve_quote", {}, OWNER))["content"][0]["text"] == "ok"


async def test_a_card_is_read_only_when_the_server_lists_it_as_a_ui_resource(hub):
    assert await hub.read_card("s", "ui://s/card.html") == CardPage("<html>", {})
    with pytest.raises(HubError, match="declares no card"):
        await hub.read_card("s", "file:///secret")


async def test_a_card_page_carries_the_ui_metadata_its_resource_declares(hub):
    page = await hub.read_card("s", "ui://s/menu.html")
    assert page == CardPage("<html>", MENU_META["ui"])


async def test_the_listing_entry_stands_in_for_a_content_item_without_metadata(hub):
    page = await hub.read_card("s", "ui://s/listed.html")
    assert page.ui == LISTED_META["ui"]


async def test_when_both_carry_metadata_the_content_item_wins(hub):
    assert (await hub.read_card("s", "ui://s/both.html")).ui == CONTENT_META["ui"]


async def test_a_card_may_come_as_a_blob_and_must_be_an_mcp_app(hub):
    assert (await hub.read_card("s", "ui://s/blob.html")).html == "<html>blob"
    with pytest.raises(HubError, match="mcp-app"):
        await hub.read_card("s", "ui://s/plain.html")


async def test_an_unknown_connector_is_refused(hub):
    with pytest.raises(HubError, match="no connector"):
        await hub.call_app_tool("other", "approve_quote", {}, OWNER)


async def test_the_client_initializes_before_its_first_request(hub):
    await hub.tools("s")
    assert [c.get("method") for c in CALLS][:2] == ["initialize", "notifications/initialized"]


async def test_a_call_inside_a_payer_group_names_it_and_no_other_call_does(hub):
    from turns.hub import GROUP_HEADER, paying_as

    await hub.call_model_tool("s__create_quote", {"a": 1}, OWNER, KEY)
    with paying_as("cd" * 16):
        await hub.call_model_tool("s__create_quote", {"a": 1}, OWNER, KEY)
    await hub.call_model_tool("s__create_quote", {"a": 1}, OWNER, KEY)
    calls = [h for h, b in zip(HEADERS, CALLS, strict=True) if b.get("method") == "tools/call"]
    assert [h.get(GROUP_HEADER) for h in calls] == [None, "cd" * 16, None]


async def test_a_call_inside_a_turn_names_its_task_and_no_other_call_does(hub):
    from turns import trace
    from turns.hub import TASK_HEADER

    await hub.call_model_tool("s__create_quote", {"a": 1}, OWNER, KEY)
    with trace.bound("chat-1", OWNER, "task-9"):
        await hub.call_model_tool("s__create_quote", {"a": 1}, OWNER, KEY)
    calls = [h for h, b in zip(HEADERS, CALLS, strict=True) if b.get("method") == "tools/call"]
    assert [h.get(TASK_HEADER) for h in calls] == [None, "task-9"]


NO_REPLY = [
    httpx.Response(502, text=""),
    httpx.Response(200, text="<html>oops</html>"),
    httpx.Response(200, json={"jsonrpc": "2.0"}),
]


@pytest.mark.parametrize("reply", NO_REPLY)
async def test_a_connector_that_sends_no_json_rpc_reply_is_one_that_could_not_be_reached(reply):
    from turns.hub import HubError

    def broken(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        return handler(request) if body.get("method") != "tools/call" else reply

    hub = Hub({"s": "http://s/mcp"}, httpx.AsyncClient(transport=httpx.MockTransport(broken)))
    with pytest.raises(HubError, match="no JSON-RPC reply"):
        await hub.call_app_tool("s", "approve_quote", {}, OWNER)
