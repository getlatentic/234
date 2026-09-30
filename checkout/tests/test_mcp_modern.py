# SPDX-License-Identifier: AGPL-3.0-or-later
"""The connectors speak two eras of MCP on one endpoint: the handshake era (2025-03-26 to 2025-11-25), as
before, and the stateless one (2026-07-28), for a request that opens in it: `server/discover`, the headers
checked against the body, results marked complete and cacheable, the errors the revision names."""

import base64
import json

import pytest

from checkout.http import handle
from tests.support import make_stack

MODERN = "2026-07-28"
META = {
    "io.modelcontextprotocol/protocolVersion": MODERN,
    "io.modelcontextprotocol/clientInfo": {"name": "test", "version": "1"},
    "io.modelcontextprotocol/clientCapabilities": {"extensions": {"io.modelcontextprotocol/ui": {}}},
}
SERVER_INFO = "io.modelcontextprotocol/serverInfo"


def body(method: str, params: dict | None = None, meta: dict | None = META) -> dict:
    merged = {**(params or {}), **({"_meta": meta} if meta is not None else {})}
    return {"jsonrpc": "2.0", "id": 1, "method": method, "params": merged}


def headers(message: dict, **over: str | None) -> dict[str, str]:
    given = {
        "mcp-protocol-version": MODERN,
        "mcp-method": message["method"],
        "accept": "application/json, text/event-stream",
    }
    name = message["params"].get("name") or message["params"].get("uri")
    if message["method"] in ("tools/call", "resources/read"):
        given["mcp-name"] = name
    given.update({k.replace("_", "-"): v for k, v in over.items()})
    return {k: v for k, v in given.items() if v is not None}


async def post(message: dict, head: dict[str, str] | None = None, connector: str = "paystack-pay"):
    stack = make_stack()
    reply = await handle(
        stack.app,
        "POST",
        f"/{connector}/mcp",
        head if head is not None else headers(message),
        json.dumps(message).encode(),
    )
    return reply, (json.loads(reply.body) if reply.body else None)


async def test_discover_names_the_versions_the_capabilities_and_the_server():
    reply, answer = await post(body("server/discover"))
    result = answer["result"]
    assert reply.status == 200 and result["resultType"] == "complete"
    assert result["supportedVersions"][0] == MODERN and "2025-11-25" in result["supportedVersions"]
    assert result["capabilities"]["extensions"]["io.modelcontextprotocol/ui"]["mimeTypes"] == [
        "text/html;profile=mcp-app"
    ]
    assert result["_meta"][SERVER_INFO]["name"] == "paystack-pay" and result["instructions"]
    assert result["ttlMs"] > 0 and result["cacheScope"] == "public"


async def test_a_modern_request_needs_no_initialize_and_no_session():
    reply, answer = await post(body("tools/list"))
    assert reply.status == 200 and "mcp-session-id" not in {k.lower() for k in reply.headers}
    result = answer["result"]
    assert result["resultType"] == "complete" and result["ttlMs"] > 0 and result["cacheScope"] == "public"
    assert {t["name"] for t in result["tools"]} >= {"create_payment_quote", "approve_quote"}
    assert result["tools"][0]["_meta"]["ui"]["resourceUri"].startswith("ui://")


async def test_a_resource_is_read_marked_complete_and_cacheable():
    message = body("resources/read", {"uri": "ui://paystack-pay/card.html"})
    reply, answer = await post(message)
    result = answer["result"]
    assert reply.status == 200 and result["resultType"] == "complete" and result["ttlMs"] > 0
    assert (
        result["contents"][0]["mimeType"] == "text/html;profile=mcp-app"
        and "<html" in result["contents"][0]["text"]
    )


async def test_a_resource_that_is_not_there_is_invalid_params_in_this_era():
    _, answer = await post(body("resources/read", {"uri": "ui://paystack-pay/nope.html"}))
    assert answer["error"]["code"] == -32602
    stack = make_stack()
    old = await handle(
        stack.app,
        "POST",
        "/paystack-pay/mcp",
        {},
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "resources/read",
                "params": {"uri": "ui://paystack-pay/nope.html"},
            }
        ).encode(),
    )
    assert json.loads(old.body)["error"]["code"] == -32002


async def test_a_tool_call_carries_its_result_with_the_card_only_meta_and_the_server_signature():
    message = body(
        "tools/call",
        {
            "name": "create_payment_quote",
            "arguments": {
                "amount_kobo": 250000,
                "amount_as_user_said": "2500",
                "description": "Lunch",
                "merchant": "Demo",
                "idempotency_key": "modern-key-000001",
            },
        },
    )
    reply, answer = await post(message)
    result = answer["result"]
    assert reply.status == 200 and result["resultType"] == "complete" and "ttlMs" not in result
    assert (
        len(result["_meta"]["approvalToken"]) == 64 and result["_meta"][SERVER_INFO]["name"] == "paystack-pay"
    )
    assert result["structuredContent"]["quote"]["phase"] == "awaiting_approval"


@pytest.mark.parametrize(
    ("what", "head", "status", "code"),
    [
        ("no version header", {"mcp_protocol_version": None}, 400, -32020),
        ("a version header that differs from _meta", {"mcp_protocol_version": "2025-11-25"}, 400, -32020),
        ("no Mcp-Method header", {"mcp_method": None}, 400, -32020),
        ("an Mcp-Method that differs from the body", {"mcp_method": "tools/call"}, 400, -32020),
    ],
)
async def test_a_header_that_is_missing_or_differs_from_the_body_is_refused(what, head, status, code):
    message = body("tools/list")
    reply, answer = await post(message, headers(message, **head))
    assert (reply.status, answer["error"]["code"]) == (status, code), what


async def test_the_name_header_must_be_there_and_match_the_body_plain_or_as_base64():
    message = body("tools/call", {"name": "get_quote_status", "arguments": {"quote_id": "qt-x"}})
    assert (await post(message, headers(message, mcp_name=None)))[0].status == 400
    assert (await post(message, headers(message, mcp_name="approve_quote")))[0].status == 400
    encoded = "=?base64?" + base64.b64encode(b"get_quote_status").decode() + "?="
    reply, _ = await post(message, headers(message, mcp_name=encoded))
    assert reply.status == 200
    reply, answer = await post(message, headers(message, mcp_name="=?base64?%%%?="))
    assert reply.status == 400 and answer["error"]["code"] == -32020


async def test_a_modern_request_must_carry_the_version_and_the_capabilities_in_meta():
    for meta in (None, {}, {"io.modelcontextprotocol/protocolVersion": MODERN}):
        message = body("tools/list", meta=meta)
        reply, answer = await post(message, headers(message))
        assert (reply.status, answer["error"]["code"]) == (400, -32602), meta


async def test_a_version_the_server_does_not_speak_names_the_ones_it_does():
    message = body("tools/list", meta={**META, "io.modelcontextprotocol/protocolVersion": "2099-01-01"})
    reply, answer = await post(message, headers(message, mcp_protocol_version="2099-01-01"))
    assert reply.status == 400 and answer["error"]["code"] == -32022
    assert (
        answer["error"]["data"]["requested"] == "2099-01-01"
        and MODERN in answer["error"]["data"]["supported"]
    )


async def test_the_methods_the_revision_removed_are_not_found_with_a_404():
    for method in ("initialize", "ping", "logging/setLevel", "resources/subscribe"):
        message = body(method)
        reply, answer = await post(message, headers(message))
        assert (reply.status, answer["error"]["code"]) == (404, -32601), method


async def test_the_handshake_era_is_unchanged():
    stack = make_stack()

    async def old(method, params=None, **head):
        message = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
        reply = await handle(stack.app, "POST", "/paystack-pay/mcp", head, json.dumps(message).encode())
        return reply.status, json.loads(reply.body)

    status, hello = await old("initialize", {"protocolVersion": "2025-11-25", "capabilities": {}})
    assert (
        status == 200
        and hello["result"]["protocolVersion"] == "2025-11-25"
        and "resultType" not in hello["result"]
    )
    status, listing = await old("tools/list", **{"mcp-protocol-version": "2025-11-25"})
    assert status == 200 and "resultType" not in listing["result"] and "ttlMs" not in listing["result"]
    status, unknown = await old("server/discover")
    assert unknown["error"]["code"] == -32601
    status, refused = await old("tools/list", **{"mcp-protocol-version": "2031-01-01"})
    assert status == 400 and refused["error"]["code"] == -32022


async def test_a_request_that_names_a_browser_origin_is_refused_unless_it_is_listed():
    stack = make_stack()
    message = json.dumps(body("tools/list")).encode()
    head = {**headers(body("tools/list")), "origin": "https://evil.example"}
    refused = await handle(stack.app, "POST", "/paystack-pay/mcp", head, message)
    assert refused.status == 403 and "origin" in json.loads(refused.body)["error"]["message"]
    allowed = make_stack(mcp_allowed_origins=("https://host.example",))
    ok = await handle(
        allowed.app, "POST", "/paystack-pay/mcp", {**head, "origin": "https://host.example"}, message
    )
    assert ok.status == 200
    none = await handle(stack.app, "POST", "/paystack-pay/mcp", headers(body("tools/list")), message)
    assert none.status == 200
