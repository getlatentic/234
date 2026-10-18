# SPDX-License-Identifier: AGPL-3.0-or-later
"""Web search through DeepSeek's Search API (web/search.py, connectors/web.py): the request it makes, what it
makes of the results, and its daily count, cache and refusals."""

import json

import pytest

from checkout.transport import Reply, TransportError
from checkout.web.search import ENDPOINT, DeepSeekSearch
from checkout.web.settings import SearchSettings, trouble
from tests.support import ScriptedTransport, make_stack

OWNER = "ab" * 16
OTHER = "cd" * 16
KEY = "sk-0123456789abcdef0123456789abcdef"
ENV = {"SEARCH_API_KEY": KEY}
RESULTS = {
    "results": [
        {
            "title": "Renewing",
            "url": "https://fixture-roads.gov.ng/renew",
            "snippet": "Renewal costs 12,500 naira, paid online before the licence runs out.",
            "summary": "# Renewing\n\nThe long summary of the page.",
            "content": "",
            "date": "2026-09-01T16:00:00+00:00",
            "authority": 4,
            "rerank_score": 2.1,
        },
        {
            "title": "News",
            "url": "https://news.example.com/a",
            "snippet": "x" * 900,
            "summary": "s",
            "date": "None",
        },
        {
            "title": "Fragment",
            "url": "https://dated.example.com/",
            "snippet": "...",
            "summary": "The summary " * 60,
        },
        {"title": "Plain http", "url": "http://insecure.example.com/", "snippet": "no" * 30},
        {"title": "Metadata", "url": "https://169.254.169.254/latest", "snippet": "no" * 30},
        {"title": "No address", "snippet": "no" * 30},
    ]
}


def deepseek(results=RESULTS, status=200, failing=False, body=None, content_type="application/json"):
    def answer(sent):
        if failing:
            return TransportError("timed out")
        if status != 200:
            return Reply(status, json.dumps(results), "application/json")
        return Reply(200, json.dumps(results) if body is None else body, content_type)

    return ScriptedTransport(answer)


def stack_with(transport, **settings):
    return make_stack(transport=transport, web_search=SearchSettings.from_env(ENV.get), **settings)


async def search(stack, query="licence renewal fee", owner=OWNER, **arguments):
    return await stack.call_as(owner, "web", "web_search", query=query, **arguments)


def code_of(result):
    assert result["isError"], result
    return result["content"][0]["text"].split(":")[0]


async def test_without_a_key_the_connector_only_fetches():
    listing = (await make_stack().mcp("web", "tools/list", owner=OWNER))["result"]["tools"]
    assert [t["name"] for t in listing] == ["web_fetch"]


async def test_with_a_key_it_also_searches_and_the_tool_reads_only():
    stack = stack_with(deepseek())
    listing = (await stack.mcp("web", "tools/list", owner=OWNER))["result"]["tools"]
    assert [t["name"] for t in listing] == ["web_fetch", "web_search"]
    assert all(t["annotations"]["readOnlyHint"] for t in listing)


async def test_a_search_is_one_post_with_the_key_as_a_bearer_and_only_the_query_and_a_count():
    transport = deepseek()
    await search(stack_with(transport), limit=3)
    (call,) = transport.calls
    assert (call.method, call.url) == ("POST", ENDPOINT)
    assert call.body == {"query": "licence renewal fee", "count": 3}
    assert call.headers["authorization"] == f"Bearer {KEY}"
    assert call.headers["user-agent"].startswith("234bot/")
    assert KEY not in json.dumps([call.url, call.body])


async def test_a_query_is_cut_to_what_the_api_takes():
    transport = deepseek()
    await DeepSeekSearch(transport, KEY).search("word " * 60, 5)
    assert len(transport.calls[0].body["query"]) <= 128
    assert transport.calls[0].body["query"] == ("word " * 60)[:128].rstrip()


async def test_the_count_is_between_one_and_ten():
    transport = deepseek()
    engine = DeepSeekSearch(transport, KEY)
    await engine.search("q", 0)
    await engine.search("q", 99)
    assert [c.body["count"] for c in transport.calls] == [1, 10]


async def test_results_are_quoted_data_with_their_address_and_day_and_unsafe_addresses_are_dropped():
    result = await search(stack_with(deepseek()))
    data = result["structuredContent"]
    assert data["untrusted"] is True and data["searched_on"].startswith("2026-")
    assert [r["url"] for r in data["results"]] == [
        "https://fixture-roads.gov.ng/renew",
        "https://news.example.com/a",
        "https://dated.example.com/",
    ]
    assert [r["published"] for r in data["results"]] == ["2026-09-01", None, None]
    text = result["content"][0]["text"]
    assert (
        "[1] Renewing — https://fixture-roads.gov.ng/renew, 2026-09-01\n"
        "> Renewal costs 12,500 naira, paid online before the licence runs out." in text
    )
    assert "169.254" not in text and "insecure" not in text and "No address" not in text


async def test_a_snippet_is_cut_and_a_thin_one_gives_way_to_the_start_of_the_summary():
    texts = [r["text"] for r in (await search(stack_with(deepseek())))["structuredContent"]["results"]]
    assert texts[0].startswith("Renewal costs") and len(texts[1]) == 500
    assert texts[2].startswith("The summary The summary") and len(texts[2]) == 500


@pytest.mark.parametrize(
    ("date", "day"),
    [
        ("2026-09-01T16:00:00+00:00", "2026-09-01"),
        ("2026-09-01", "2026-09-01"),
        ("None", None),
        (None, None),
        ("", None),
        ("01:14PM, Friday, August 14 2026, PDT", None),
        ("unknown", None),
        (20260901, None),
    ],
)
async def test_only_an_iso_day_counts_as_a_publication_day(date, day):
    item = {"title": "T", "url": "https://a.example.com/", "snippet": "s" * 60, "date": date}
    found = await DeepSeekSearch(deepseek({"results": [item]}), KEY).search("q", 5)
    assert [h.published for h in found] == [day]


async def test_no_results_say_so():
    result = await search(stack_with(deepseek({"results": []})))
    assert result["content"][0]["text"].startswith('No web results for "licence renewal fee"')


async def test_the_same_question_within_the_hour_is_not_asked_again_and_costs_no_search():
    transport = deepseek()
    stack = stack_with(transport)
    await search(stack)
    again = await search(stack, query="  Licence  RENEWAL fee ")
    assert len(again["structuredContent"]["results"]) == 3
    assert len(transport.calls) == 1
    assert await stack.db.row("SELECT used FROM web_search_use") == {"used": 1}


async def test_a_person_has_a_few_searches_a_day_and_a_new_day_gives_them_back():
    transport = deepseek()
    settings = SearchSettings.from_env({**ENV, "SEARCHES_PER_DAY": "2"}.get)
    stack = make_stack(transport=transport, web_search=settings)
    await search(stack, "one")
    await search(stack, "two")
    refused = await search(stack, "three")
    assert code_of(refused) == "SEARCH_LIMIT" and len(transport.calls) == 2
    other = await search(stack, "three", owner=OTHER)
    assert not other.get("isError")
    stack.clock.advance(86_400)
    assert not (await search(stack, "three")).get("isError")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"failing": True},
        {"status": 402},
        {"status": 408},
        {"status": 429},
        {"status": 500},
        {"status": 503},
        {"body": "<html>blocked</html>", "content_type": "text/html"},
        {"body": "[]"},
        {"body": '{"error": "x"}'},
        {"body": '{"results": "none"}'},
    ],
)
async def test_an_api_that_fails_gives_a_refusal_that_says_nothing_of_it(kwargs):
    result = await search(stack_with(deepseek(**kwargs)))
    text = result["content"][0]["text"]
    assert code_of(result) == "SEARCH_UNAVAILABLE"
    assert text == "SEARCH_UNAVAILABLE: Web search did not answer. Say so, and do not answer from memory."


async def test_after_a_failure_the_next_search_asks_again():
    state = {"down": True}
    inner = deepseek()

    def answer(sent):
        return TransportError("down") if state["down"] else inner._answer(sent)

    stack = stack_with(ScriptedTransport(answer))
    assert code_of(await search(stack)) == "SEARCH_UNAVAILABLE"
    state["down"] = False
    assert not (await search(stack, "again")).get("isError")


def test_the_settings_need_the_key_and_never_stop_the_worker():
    assert SearchSettings.from_env({}.get) is None and trouble({}.get) is None
    only_address = {"SEARCH_URL": ENDPOINT}
    assert SearchSettings.from_env(only_address.get) is None and "SEARCH_API_KEY not set" in trouble(
        only_address.get
    )
    blank = {"SEARCH_API_KEY": "  "}
    assert SearchSettings.from_env(blank.get) is None and trouble(blank.get) is None
    for spaced in ("sk-1 2", "sk-1\n2", "sk-é"):
        wrong = {"SEARCH_API_KEY": spaced}
        assert SearchSettings.from_env(wrong.get) is None and "web search is off" in trouble(wrong.get)
    found = SearchSettings.from_env(ENV.get)
    assert found and found.per_day == 30 and found.url == ENDPOINT and KEY not in repr(found)
    assert trouble(ENV.get) is None


@pytest.mark.parametrize(
    "address",
    [
        "http://api.deepseek.com/v1/tools/search",
        "https://api.deepseek.com.evil.com/v1/tools/search",
        "https://evil.com/api.deepseek.com",
        "https://api.deepseek.com@evil.com/v1/tools/search",
        "https://evil.com@api.deepseek.com/v1/tools/search",
        "https://api.deepseek.com:8443/v1/tools/search",
        "https://api.deepseek.com:bad/v1/tools/search",
        "https://example.com/",
        "api.deepseek.com",
    ],
)
def test_the_key_is_sent_only_to_deepseeks_host_over_https(address):
    wrong = {**ENV, "SEARCH_URL": address}
    assert SearchSettings.from_env(wrong.get) is None and "web search is off" in trouble(wrong.get)


def test_another_path_on_deepseeks_host_is_allowed_and_a_bad_daily_count_is_not():
    other = {**ENV, "SEARCH_URL": "https://api.deepseek.com:443/v2/tools/search"}
    assert SearchSettings.from_env(other.get).url == "https://api.deepseek.com:443/v2/tools/search"
    for bad in ("0", "-1", "many"):
        zero = {**ENV, "SEARCHES_PER_DAY": bad}
        assert SearchSettings.from_env(zero.get) is None and "SEARCHES_PER_DAY" in trouble(zero.get)
    assert SearchSettings.from_env({**ENV, "SEARCHES_PER_DAY": "5"}.get).per_day == 5


async def test_the_address_the_settings_name_is_the_one_called():
    transport = deepseek()
    settings = SearchSettings.from_env({**ENV, "SEARCH_URL": "https://api.deepseek.com/v2/tools/search"}.get)
    await search(make_stack(transport=transport, web_search=settings))
    assert transport.calls[0].url == "https://api.deepseek.com/v2/tools/search"


async def test_a_query_longer_than_the_api_takes_is_refused_to_the_model_before_it_is_counted():
    transport = deepseek()
    stack = stack_with(transport)
    result = await search(stack, query="q" * 129)
    assert result["isError"] and not transport.calls
    assert await stack.db.row("SELECT used FROM web_search_use") is None
