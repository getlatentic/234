# SPDX-License-Identifier: AGPL-3.0-or-later
"""The model is not offered the idempotency key and cannot choose it: the hub leaves the field out of the
schema it shows and puts the host's key into the call, over anything the model sent."""

import json

import httpx
import pytest

from turns.hub import Hub

OWNER = "ab" * 16
KEY = "host-derived-key-0123456789abcdef01234567"
KEYED = {
    "type": "object",
    "additionalProperties": False,
    "$schema": "x",
    "properties": {
        "amount": {"type": "integer"},
        "idempotency_key": {"type": "string", "minLength": 8, "pattern": "^[A-Za-z0-9._:-]+$"},
    },
    "required": ["amount", "idempotency_key"],
}
PLAIN = {"type": "object", "properties": {"network": {"type": "string"}}, "required": ["network"]}
MODEL, APP = {"ui": {"visibility": ["model"]}}, {"ui": {"visibility": ["app"]}}
TOOLS = [
    {"name": "create_quote", "description": "d", "inputSchema": KEYED, "_meta": MODEL},
    {"name": "list_plans", "description": "d", "inputSchema": PLAIN, "_meta": MODEL},
    {"name": "order", "description": "d", "inputSchema": KEYED, "_meta": APP},
    {"name": "no_schema", "description": "d", "inputSchema": {"type": "object"}},
]
CALLS: list[dict] = []


def handler(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    method = body.get("method")
    if method == "tools/call":
        CALLS.append(body["params"])
    result = {
        "tools/list": {"tools": TOOLS},
        "tools/call": {"content": [{"type": "text", "text": "ok"}]},
    }.get(method)
    if result is None:
        return httpx.Response(202)
    return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})


@pytest.fixture
def hub():
    CALLS.clear()
    return Hub({"s": "http://s/mcp"}, httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def offered(tools: list[dict], name: str) -> dict:
    return next(t["function"]["parameters"] for t in tools if t["function"]["name"] == f"s__{name}")


async def test_the_schema_the_model_is_shown_lacks_the_key_in_its_properties_and_in_required(hub):
    schema = offered(await hub.model_tools(), "create_quote")
    assert set(schema["properties"]) == {"amount"} and schema["required"] == ["amount"]
    assert schema["additionalProperties"] is False and "$schema" not in schema


async def test_no_model_facing_schema_carries_the_key_anywhere(hub):
    assert "idempotency_key" not in json.dumps(await hub.model_tools())


async def test_a_tool_without_a_key_is_shown_as_it_is_and_one_without_properties_is_shown_too(hub):
    tools = await hub.model_tools()
    assert offered(tools, "list_plans") == PLAIN
    assert offered(tools, "no_schema") == {"type": "object"}


async def test_the_connectors_own_listing_keeps_the_key_for_the_clients_that_use_it(hub):
    await hub.model_tools()
    listed = {t["name"]: t for t in await hub.tools("s")}
    assert "idempotency_key" in listed["create_quote"]["inputSchema"]["properties"]
    assert listed["create_quote"]["inputSchema"]["required"] == ["amount", "idempotency_key"]
    assert KEYED["required"] == ["amount", "idempotency_key"] and "$schema" in KEYED


async def test_the_key_of_the_host_is_sent_when_the_model_sent_none(hub):
    await hub.call_model_tool("s__create_quote", {"amount": 5}, OWNER, KEY)
    assert CALLS == [{"name": "create_quote", "arguments": {"amount": 5, "idempotency_key": KEY}}]


async def test_the_key_of_the_host_overwrites_one_the_model_still_sends(hub):
    await hub.call_model_tool(
        "s__create_quote", {"amount": 5, "idempotency_key": "a1b2c3d4e5f6g7h8i9j0"}, OWNER, KEY
    )
    assert CALLS[0]["arguments"] == {"amount": 5, "idempotency_key": KEY}


async def test_the_callers_arguments_are_not_changed_by_the_call(hub):
    mine = {"amount": 5, "idempotency_key": "model"}
    await hub.call_model_tool("s__create_quote", mine, OWNER, KEY)
    assert mine == {"amount": 5, "idempotency_key": "model"}


async def test_a_tool_that_takes_no_key_is_sent_none(hub):
    await hub.call_model_tool("s__list_plans", {"network": "mtn"}, OWNER, KEY)
    await hub.call_model_tool("s__no_schema", {}, OWNER, KEY)
    assert [c["arguments"] for c in CALLS] == [{"network": "mtn"}, {}]


async def test_a_card_keeps_the_key_it_sends(hub):
    await hub.call_app_tool("s", "order", {"amount": 5, "idempotency_key": "menu-card-0001"}, OWNER)
    assert CALLS[0]["arguments"] == {"amount": 5, "idempotency_key": "menu-card-0001"}


async def test_the_hub_says_which_tools_take_a_key_and_none_for_what_does_not_exist(hub):
    assert [await hub.keyed(f"s__{n}") for n in ("create_quote", "order", "list_plans", "nope")] == [
        True, True, False, False,
    ]  # fmt: skip
    assert not await hub.keyed("x__create_quote")


def _listing(tools: list[dict]):
    def answer(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        result = {"tools/list": {"tools": tools}}.get(body.get("method"))
        if result is None:
            return httpx.Response(202)
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})

    return answer


TRANSFER = {
    "type": "object",
    "properties": {
        "account_number": {"type": "string"},
        "bank": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "bank_code": {"anyOf": [{"type": "string"}, {"type": "null"}], "x-model-hidden": True},
        "idempotency_key": {"type": "string"},
    },
    "required": ["account_number", "idempotency_key"],
    "x-model-required": ["bank"],
}


async def test_a_property_the_connector_hides_is_not_shown_and_one_it_requires_of_the_model_is_required():
    tools = [{"name": "transfer", "description": "d", "inputSchema": TRANSFER, "_meta": MODEL}]
    hub = Hub({"s": "http://s/mcp"}, httpx.AsyncClient(transport=httpx.MockTransport(_listing(tools))))
    schema = offered(await hub.model_tools(), "transfer")
    assert set(schema["properties"]) == {"account_number", "bank"}
    assert schema["required"] == ["account_number", "bank"]
    assert "x-model-required" not in schema and "x-model-hidden" not in json.dumps(schema)
    assert "bank_code" in TRANSFER["properties"] and TRANSFER["required"] == [
        "account_number",
        "idempotency_key",
    ]
