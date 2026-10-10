# SPDX-License-Identifier: AGPL-3.0-or-later
"""Web search through an AgentCore Gateway (web/search.py, connectors/web.py): the signed MCP calls it makes,
what it makes of the results, and its daily count, cache and refusals."""

import json

import pytest

from checkout.transport import Reply, TransportError
from checkout.web.settings import SearchSettings, trouble
from tests.support import ScriptedTransport, json_reply, make_stack

OWNER = "ab" * 16
OTHER = "cd" * 16
GATEWAY = "https://gw-abc123.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp"
KEY, SECRET = "AKIAEXAMPLEKEY12345", "s3cr3t/ExampleSecretKeyValue+0123456789abcd"
ENV = {"SEARCH_GATEWAY_URL": GATEWAY, "AWS_ACCESS_KEY_ID": KEY, "AWS_SECRET_ACCESS_KEY": SECRET}
RESULTS = {
    "results": [
        {
            "text": "Renewal costs 12,500 naira.",
            "url": "https://fixture-roads.gov.ng/renew",
            "title": "Renewing",
            "publishedDate": "2026-09-01T00:00:00Z",
        },
        {"text": "x" * 900, "url": "https://news.example.com/a", "title": "News", "publishedDate": "unknown"},
        {
            "text": "x",
            "url": "https://dated.example.com/",
            "title": "Odd",
            "publishedDate": "01:14PM, Friday, August 14 2026, PDT",
        },
        {"text": "no", "url": "http://insecure.example.com/", "title": "Plain http"},
        {"text": "no", "url": "https://169.254.169.254/latest", "title": "Metadata"},
    ]
}


def gateway(results=RESULTS, as_text=False, event_stream=False, status=200, failing=False):
    def answer(sent):
        if failing:
            return TransportError("timed out")
        method = sent.body.get("method")
        if method == "notifications/initialized":
            return Reply(202, "", None)
        if status != 200:
            return Reply(status, "denied", "text/plain")
        if method == "initialize":
            message = {"jsonrpc": "2.0", "id": sent.body["id"], "result": {"protocolVersion": "2025-03-26"}}
        else:
            result = (
                {"content": [{"type": "text", "text": json.dumps(results)}]}
                if as_text
                else {"content": [], "structuredContent": results}
            )
            message = {"jsonrpc": "2.0", "id": sent.body["id"], "result": result}
        if event_stream:
            return Reply(200, f"event: message\ndata: {json.dumps(message)}\n\n", "text/event-stream")
        return json_reply(message)

    return ScriptedTransport(answer)


def stack_with(transport, **settings):
    return make_stack(transport=transport, web_search=SearchSettings.from_env(ENV.get), **settings)


async def search(stack, query="licence renewal fee", owner=OWNER, **arguments):
    return await stack.call_as(owner, "web", "web_search", query=query, **arguments)


def code_of(result):
    assert result["isError"], result
    return result["content"][0]["text"].split(":")[0]


async def test_without_a_gateway_the_connector_only_fetches():
    listing = (await make_stack().mcp("web", "tools/list", owner=OWNER))["result"]["tools"]
    assert [t["name"] for t in listing] == ["web_fetch"]


async def test_with_a_gateway_it_also_searches_and_the_tool_reads_only():
    stack = stack_with(gateway())
    listing = (await stack.mcp("web", "tools/list", owner=OWNER))["result"]["tools"]
    assert [t["name"] for t in listing] == ["web_fetch", "web_search"]
    assert all(t["annotations"]["readOnlyHint"] for t in listing)


async def test_a_search_makes_signed_mcp_calls_to_the_gateway_and_leaks_no_secret():
    transport = gateway()
    await search(stack_with(transport), limit=3)
    methods = [c.body.get("method") for c in transport.calls]
    assert methods == ["initialize", "notifications/initialized", "tools/call"]
    call = transport.calls[-1]
    assert call.body["params"] == {
        "name": "web-search-tool___WebSearch",
        "arguments": {"query": "licence renewal fee", "maxResults": 3},
    }
    assert call.url == GATEWAY and "host" not in call.headers
    assert call.headers["authorization"].startswith(f"AWS4-HMAC-SHA256 Credential={KEY}/")
    assert "/us-east-1/bedrock-agentcore/aws4_request" in call.headers["authorization"]
    assert call.headers["mcp-protocol-version"] == "2025-03-26" and "x-amz-date" in call.headers
    everything = json.dumps([[c.url, c.headers, c.body] for c in transport.calls])
    assert SECRET not in everything


async def test_results_are_quoted_data_with_their_address_and_day_and_unsafe_addresses_are_dropped():
    result = await search(stack_with(gateway()))
    data = result["structuredContent"]
    assert data["untrusted"] is True and data["searched_on"].startswith("2026-")
    assert [r["url"] for r in data["results"]] == [
        "https://fixture-roads.gov.ng/renew",
        "https://news.example.com/a",
        "https://dated.example.com/",
    ]
    assert [r["published"] for r in data["results"]] == ["2026-09-01", None, None]
    assert len(data["results"][1]["text"]) == 500
    text = result["content"][0]["text"]
    assert (
        "[1] Renewing — https://fixture-roads.gov.ng/renew, 2026-09-01\n> Renewal costs 12,500 naira." in text
    )
    assert "169.254" not in text and "insecure" not in text


@pytest.mark.parametrize(
    "kind", [{"as_text": True}, {"event_stream": True}, {"as_text": True, "event_stream": True}]
)
async def test_the_result_may_come_as_json_text_or_as_a_server_sent_event(kind):
    result = await search(stack_with(gateway(**kind)))
    assert len(result["structuredContent"]["results"]) == 3


async def test_no_results_say_so():
    result = await search(stack_with(gateway({"results": []})))
    assert result["content"][0]["text"].startswith('No web results for "licence renewal fee"')


async def test_the_same_question_within_the_hour_is_not_asked_again_and_costs_no_search():
    transport = gateway()
    stack = stack_with(
        transport,
    )
    await search(stack)
    again = await search(stack, query="  Licence  RENEWAL fee ")
    assert len(again["structuredContent"]["results"]) == 3
    assert [c.body.get("method") for c in transport.calls].count("tools/call") == 1
    assert await stack.db.row("SELECT used FROM web_search_use") == {"used": 1}


async def test_a_person_has_a_few_searches_a_day_and_a_new_day_gives_them_back():
    transport = gateway()
    settings = SearchSettings.from_env({**ENV, "SEARCHES_PER_DAY": "2"}.get)
    stack = make_stack(transport=transport, web_search=settings)
    await search(stack, "one")
    await search(stack, "two")
    refused = await search(stack, "three")
    assert (
        code_of(refused) == "SEARCH_LIMIT"
        and [c.body.get("method") for c in transport.calls].count("tools/call") == 2
    )
    other = await search(stack, "three", owner=OTHER)
    assert not other.get("isError")
    stack.clock.advance(86_400)
    assert not (await search(stack, "three")).get("isError")


@pytest.mark.parametrize("kwargs", [{"failing": True}, {"status": 403}, {"status": 500}])
async def test_a_gateway_that_fails_gives_a_refusal_that_says_nothing_of_it(kwargs):
    result = await search(stack_with(gateway(**kwargs)))
    assert code_of(result) == "SEARCH_UNAVAILABLE"
    assert "denied" not in result["content"][0]["text"] and KEY not in result["content"][0]["text"]


async def test_after_a_failure_the_next_search_shakes_hands_again():
    state = {"down": True}
    inner = gateway()

    def answer(sent):
        return TransportError("down") if state["down"] else inner._answer(sent)

    transport = ScriptedTransport(answer)
    stack = stack_with(transport)
    assert code_of(await search(stack)) == "SEARCH_UNAVAILABLE"
    state["down"] = False
    assert not (await search(stack, "again")).get("isError")


def test_the_gateway_settings_are_all_or_none_and_never_stop_the_worker():
    assert SearchSettings.from_env({}.get) is None and trouble({}.get) is None
    for partial in (
        {"SEARCH_GATEWAY_URL": GATEWAY},
        {"AWS_ACCESS_KEY_ID": KEY},
        {**ENV, "AWS_SECRET_ACCESS_KEY": ""},
    ):
        assert SearchSettings.from_env(partial.get) is None and "not set" in trouble(partial.get)
    for bad in (
        "http://gw.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp",
        "https://gw.gateway.bedrock-agentcore.us-east-1.amazonaws.com.evil.com/mcp",
        "https://evil.com/gw.gateway.bedrock-agentcore.us-east-1.amazonaws.com",
        "https://gw.gateway.bedrock-agentcore.eu-west-1.amazonaws.com/mcp",
    ):
        wrong = {**ENV, "SEARCH_GATEWAY_URL": bad}
        assert SearchSettings.from_env(wrong.get) is None and "web search is off" in trouble(wrong.get)
    zero = {**ENV, "SEARCHES_PER_DAY": "0"}
    assert SearchSettings.from_env(zero.get) is None and "SEARCHES_PER_DAY" in trouble(zero.get)
    found = SearchSettings.from_env(ENV.get)
    assert found and found.per_day == 30 and found.target == "web-search-tool" and SECRET not in repr(found)
    assert trouble(ENV.get) is None


async def test_a_gateway_that_answers_with_an_error_result_gives_a_refusal():
    def answer(sent):
        if sent.body.get("method") == "notifications/initialized":
            return Reply(202, "", None)
        result = (
            {"protocolVersion": "2025-03-26"}
            if sent.body["method"] == "initialize"
            else {"isError": True, "content": []}
        )
        return json_reply({"jsonrpc": "2.0", "id": sent.body["id"], "result": result})

    assert code_of(await search(stack_with(ScriptedTransport(answer)))) == "SEARCH_UNAVAILABLE"


async def test_when_a_call_fails_after_the_handshake_the_next_search_shakes_hands_again():
    inner = gateway()
    state = {"calls": 0}

    def answer(sent):
        if sent.body.get("method") == "tools/call":
            state["calls"] += 1
            if state["calls"] == 1:
                return Reply(500, "boom", "text/plain")
        return inner._answer(sent)

    transport = ScriptedTransport(answer)
    stack = stack_with(transport)
    assert code_of(await search(stack)) == "SEARCH_UNAVAILABLE"
    assert not (await search(stack, "second")).get("isError")
    assert [c.body.get("method") for c in transport.calls].count("initialize") == 2
