# SPDX-License-Identifier: AGPL-3.0-or-later
"""Idempotency keys against the running Workers (local workerd and D1) with the real connectors: the model is
not offered a key and cannot reuse one, buying the same thing again is a new quote wherever it is asked, a
request repeated inside one reply is made once, and the ledger hands a retried call its own quote back.
Run with the stack up (`pytest -m worker`); CHECKOUT_URL names the connector Worker."""

import json
import os

import httpx
import pytest

from turns.calls import REPEATED
from turns.hub import build_hub
from turns.idempotency import derive_key

from .worker_client import FAKE_MODEL, Visitor, finished, reset_budget, until

pytestmark = pytest.mark.worker
CHECKOUT = os.environ.get("CHECKOUT_URL", "http://localhost:8900")
AIRTIME = "airtime 500 to 07031234567 on mtn"
OWNER = "ab" * 16
QUOTE_TOOLS = {"create_airtime_quote", "create_data_quote", "create_transfer_quote", "create_payment_quote"}


@pytest.fixture(autouse=True)
async def fresh_budget():
    await reset_budget()


async def ask(v: Visitor, chat: str, text: str) -> list[dict]:
    """Sends a message and returns the chat's log once the turn that answered it has finished."""
    sent = (await v.send(chat, text)).json()["seq"]
    return await until(v.sse(chat), lambda e: finished(e) and e["seq"] > sent)


def quotes(log: list[dict]) -> list[str]:
    return [e["ref"] for e in log if e["type"] == "card"]


def tool_events(log: list[dict]) -> list[dict]:
    return [e["payload"] for e in log if e["type"] == "tool"]


async def test_the_model_is_offered_quote_tools_without_an_idempotency_key():
    async with Visitor() as v, httpx.AsyncClient() as model:
        await model.get(f"{FAKE_MODEL}/v1/_reset")
        await ask(v, await v.new_chat(), "Pay ₦2,500 to Demo Kitchen for lunch")
        offered = [
            r["tools"] for r in (await model.get(f"{FAKE_MODEL}/v1/_requests")).json() if r.get("tools")
        ]
    assert offered and all("idempotency_key" not in json.dumps(tools) for tools in offered)
    names = {t["function"]["name"].split("__")[-1] for t in offered[0]}
    assert names >= QUOTE_TOOLS


async def test_the_same_purchase_twice_in_one_chat_is_two_quotes_even_when_the_model_reuses_its_key():
    async with Visitor() as v:
        chat = await v.new_chat()
        await ask(v, chat, f"reuse key: {AIRTIME}")
        log = await ask(v, chat, f"reuse key: {AIRTIME}")
    sent = {t["arguments"]["idempotency_key"] for t in tool_events(log)}
    assert sent == {"reused-key-0001"}
    assert len(quotes(log)) == 2 and len(set(quotes(log))) == 2
    assert not any(t["is_error"] for t in tool_events(log))


async def test_the_same_purchase_in_two_chats_of_one_visitor_is_two_quotes():
    async with Visitor() as v:
        first = quotes(await ask(v, await v.new_chat(), f"reuse key: {AIRTIME}"))
        second = quotes(await ask(v, await v.new_chat(), f"reuse key: {AIRTIME}"))
    assert len(first) == len(second) == 1 and first != second


async def test_the_same_purchase_by_two_visitors_is_two_quotes():
    async with Visitor() as a, Visitor() as b:
        first = quotes(await ask(a, await a.new_chat(), f"reuse key: {AIRTIME}"))
        second = quotes(await ask(b, await b.new_chat(), f"reuse key: {AIRTIME}"))
    assert len(first) == len(second) == 1 and first != second


async def test_the_same_request_twice_in_one_reply_is_made_once_and_the_model_is_told():
    async with Visitor() as v:
        chat = await v.new_chat()
        log = await ask(v, chat, f"twice: {AIRTIME}")
        first, second = tool_events(log)
        assert len(quotes(log)) == 1 and not first["is_error"] and not second["is_error"]
        assert second["result_text"] == REPEATED + first["result_text"]
        again = await ask(v, chat, AIRTIME)
    assert len(set(quotes(again))) == 2


async def test_a_retried_call_gets_its_own_quote_back_and_anything_else_a_new_one_or_a_refusal():
    async with httpx.AsyncClient(timeout=30) as client:
        hub = build_hub(CHECKOUT, ("airtime",), client)
        key = derive_key(OWNER, "c" * 32, "call_abc")
        request = {
            "network": "mtn",
            "phone": "07031234567",
            "amount_kobo": 50000,
            "amount_as_user_said": "₦500",
        }
        first = await hub.call_model_tool("airtime__create_airtime_quote", request, OWNER, key)
        retried = await hub.call_model_tool("airtime__create_airtime_quote", dict(request), OWNER, key)
        fresh = await hub.call_model_tool(
            "airtime__create_airtime_quote", request, OWNER, derive_key(OWNER, "c" * 32, "call_def")
        )
        changed = await hub.call_model_tool(
            "airtime__create_airtime_quote",
            {**request, "amount_kobo": 60000, "amount_as_user_said": "₦600"},
            OWNER,
            key,
        )
    quote = lambda outcome: outcome.result["structuredContent"]["quote"]["id"]  # noqa: E731
    assert not first.is_error and quote(retried) == quote(first) and quote(fresh) != quote(first)
    assert changed.is_error and "IDEMPOTENCY_CONFLICT" in json.dumps(changed.result)
