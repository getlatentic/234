# SPDX-License-Identifier: AGPL-3.0-or-later
"""The host reaches the connectors through a service binding: the request goes out by the binding's
`fetch` and the reply comes back as an ordinary httpx response."""

import json
from email.message import Message

import httpx
import pytest

from turns.binding import ServiceBindingTransport, connector_client, response_headers
from turns.hub import Hub, McpHttp


class FakeReply:
    def __init__(self, status: int, body: bytes, **headers: str) -> None:
        self.status = status
        self.headers = Message()
        for name, value in headers.items():
            self.headers[name.replace("_", "-")] = value
        self._body = body

    async def bytes(self) -> bytes:
        return self._body


class FakeBinding:
    def __init__(self, reply: FakeReply) -> None:
        self.reply = reply
        self.sent: list[dict] = []

    async def fetch(self, url: str, **options) -> FakeReply:
        self.sent.append({"url": url, **options})
        return self.reply


async def test_a_request_goes_out_by_the_binding_with_its_method_headers_and_body():
    binding = FakeBinding(FakeReply(200, b'{"ok": true}', content_type="application/json"))
    client = httpx.AsyncClient(transport=ServiceBindingTransport(binding))
    answer = await client.post(
        "https://checkout-mcp.internal/a/mcp", json={"x": 1}, headers={"authorization": "Bearer t"}
    )
    sent = binding.sent[0]
    assert (sent["url"], sent["method"]) == ("https://checkout-mcp.internal/a/mcp", "POST")
    assert sent["headers"]["authorization"] == "Bearer t"
    assert json.loads(sent["body"]) == {"x": 1}
    assert (answer.status_code, answer.json()) == (200, {"ok": True})


async def test_the_owner_header_of_a_tool_call_reaches_the_connectors_through_the_binding():
    ok = FakeReply(200, b'{"jsonrpc":"2.0","id":1,"result":{"content":[]}}', content_type="application/json")
    binding = FakeBinding(ok)
    client = httpx.AsyncClient(transport=ServiceBindingTransport(binding))
    await McpHttp("https://checkout-mcp.internal/s/mcp", client, "t").request(
        "tools/call", {"name": "approve_quote", "arguments": {}}, "ab" * 16
    )
    call = next(s for s in binding.sent if json.loads(s["body"]).get("method") == "tools/call")
    assert call["headers"]["x-ledger-owner"] == "ab" * 16
    assert call["headers"]["authorization"] == "Bearer t"
    assert all("x-ledger-owner" not in s["headers"] for s in binding.sent if s is not call)


async def test_a_reply_without_a_body_and_an_error_status_come_through():
    binding = FakeBinding(FakeReply(401, b"Unauthorized", www_authenticate="Bearer"))
    client = httpx.AsyncClient(transport=ServiceBindingTransport(binding))
    answer = await client.get("https://checkout-mcp.internal/health")
    assert binding.sent[0]["body"] is None
    assert (answer.status_code, answer.text, answer.headers["www-authenticate"]) == (
        401,
        "Unauthorized",
        "Bearer",
    )


def test_headers_that_describe_the_wire_are_dropped():
    kept = response_headers([("Content-Encoding", "gzip"), ("content-length", "9"), ("x-a", "1")])
    assert kept == [("x-a", "1")]


async def test_a_hub_talks_to_a_connector_through_the_binding():
    result = {"jsonrpc": "2.0", "id": 1, "result": {"tools": [{"name": "t"}]}}
    binding = FakeBinding(FakeReply(200, json.dumps(result).encode(), content_type="application/json"))
    hub = Hub(
        {"s": "https://checkout-mcp.internal/s/mcp"}, connector_client(_env(binding), "SVC", None), "tok"
    )
    assert await hub.tools("s") == [{"name": "t"}]
    assert {call["headers"]["authorization"] for call in binding.sent} == {"Bearer tok"}


def _env(binding):
    class Env:
        SVC = binding

    return Env()


def test_without_a_binding_name_the_ordinary_client_is_used():
    ordinary = httpx.AsyncClient()
    assert connector_client(_env(None), "", ordinary) is ordinary


def test_a_named_binding_that_is_missing_stops_the_host_instead_of_falling_back_to_the_network():
    with pytest.raises(RuntimeError, match="MISSING"):
        connector_client(_env(None), "MISSING", httpx.AsyncClient())
