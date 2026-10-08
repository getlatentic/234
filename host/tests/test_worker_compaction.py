# SPDX-License-Identifier: AGPL-3.0-or-later
"""Compaction on the running stack (local workerd, local D1, the real connectors, the scripted model): a long
chat in Pidgin and English with quotes in several states is compacted as it grows, keeps every fact, keeps the
quote still waiting for the person actionable, answers a question about its past after the compactions, and
leaves the log whole.

Needs the stack up with a small context window:
  CONTEXT_WINDOW_TOKENS=8000 COMPACT_AT=0.75 KEEP_RECENT_TOKENS=500 tools/up.sh
(the tool definitions alone are about 3,000 tokens, so a window this small compacts a chat of a few dozen
messages several times). The host lets a visitor send twelve messages a minute, which is what makes the run
take minutes. Run with `pytest -m worker tests/test_worker_compaction.py`."""

import asyncio
import json
import os

import httpx
import pytest

from turns.compaction import facts
from turns.eventlog import Event

from .long_chat import LongChat, talk
from .worker_client import FAKE_MODEL, HOST, Visitor, reset_budget

pytestmark = pytest.mark.worker
CHECKOUT = os.environ.get("CHECKOUT_URL", "http://localhost:8900")
THRESHOLD = 6000
TURNS, EVERY = 36, 6


@pytest.fixture(autouse=True)
async def clean_stack():
    await reset_budget()
    async with httpx.AsyncClient() as http:
        await http.get(f"{FAKE_MODEL}/v1/_reset")
        await http.post(f"{FAKE_MODEL}/v1/_config", json={"word_delay": 0})
        assert (await http.post(f"{CHECKOUT}/test/reset")).status_code == 200
    yield
    async with httpx.AsyncClient() as http:
        await http.get(f"{FAKE_MODEL}/v1/_reset")


def as_events(wire: list[dict]) -> list[Event]:
    return [Event(e["seq"], e["type"], e["task"], e["ref"], e["payload"], e["at"]) for e in wire]


def model_requests() -> list[dict]:
    return httpx.get(f"{FAKE_MODEL}/v1/_requests").json()


async def play(chat: LongChat) -> dict[str, str]:
    """Every sixth turn buys airtime: paid, declined or (the last) left open."""
    states: dict[str, str] = {}
    quote = 0
    for n in range(TURNS):
        if n % EVERY == EVERY - 1:
            await chat.say(f"airtime {650 + 50 * quote} to 0703123456{quote} on mtn")
            card = chat.cards()[-1]
            ref = card["ref"]
            if quote == TURNS // EVERY - 1:
                states[ref] = "awaiting_approval"
            elif quote % 2 == 0:
                await chat.pay(card)
                states[ref] = "succeeded"
            else:
                await chat.decline(card)
                states[ref] = "declined"
            quote += 1
        else:
            await chat.say(talk(n))
    return states


async def test_a_long_chat_is_compacted_keeps_its_facts_and_answers_about_its_past():
    async with Visitor(HOST) as v, LongChat.open(v) as chat:
        states = await play(chat)
        compactions = chat.compactions()
        assert len(compactions) >= 3
        assert all(
            c["payload"]["trigger"] == "auto" and c["payload"]["verified"] == "model" for c in compactions
        )
        assert all(c["payload"]["tokens"]["after"] < c["payload"]["tokens"]["before"] for c in compactions)
        assert all(c["task"] is None and c["ref"].startswith("compaction:") for c in compactions)

        log = await v.log(chat.chat)
        assert [e["seq"] for e in log] == list(range(1, len(log) + 1)), "the log has a gap"
        assert log == chat.events, "the socket and the log disagree"
        events = as_events(log)
        assert sum(e.type == "user" for e in events) == TURNS + 1

        sizes = [e["payload"]["usage"]["prompt_tokens"] for e in log if e["type"] == "assistant"]
        assert max(sizes) <= THRESHOLD * 1.15, f"a request of {max(sizes)} tokens went out"

        covered = []
        for compaction in as_events(chat.compactions()):
            last = compaction.payload["covers"]["last"]
            needed = facts.facts_of_events([e for e in events if e.seq <= last])
            kept = facts.facts_of_events([e for e in events if e.seq > last])
            assert not facts.missing_from(compaction.payload["summary"], needed, kept)
            covered.append(needed)
        # An early compaction may cover small talk only; the later ones cover the payments.
        assert len([f for f in covered if f.amounts and f.phones]) >= 2

        (open_ref,) = [ref for ref, phase in states.items() if phase == "awaiting_approval"]
        last_request = json.dumps(model_requests()[-1]["messages"], ensure_ascii=False)
        assert open_ref in last_request, "the quote waiting for the person is not in front of the model"

        card = next(c for c in chat.cards() if c["ref"] == open_ref)
        kobo = card["payload"]["result"]["structuredContent"]["quote"]["amount"]["kobo"]
        approved = await chat.call(
            card, "approve_quote", {"displayed_amount_kobo": kobo, "readback_confirmed": True}
        )
        assert approved["structuredContent"]["quote"]["phase"] == "awaiting_checkout"

        answer = await chat.say("what was the last amount I paid?")
        paid = [ref for ref, phase in states.items() if phase == "succeeded"]
        last_paid = next(c for c in chat.cards() if c["ref"] == paid[-1])
        shown = last_paid["payload"]["result"]["structuredContent"]["quote"]["amount"]["display"].split(".")[
            0
        ]
        reply = next(e for e in reversed(answer) if e["type"] == "assistant")["payload"]["text"]
        assert shown in reply, f"{shown} not in {reply!r}"
        summary = model_requests()[-1]["messages"][1]["content"]
        assert summary.startswith("[Summary of the earlier conversation")

        secrets = [c["payload"]["result"]["_meta"]["approvalToken"] for c in chat.cards()]
        for event in chat.events:
            quote = event["payload"].get("result", {}).get("structuredContent", {}).get("quote", {})
            secrets += [quote["checkoutUrl"]] if quote.get("checkoutUrl") else []
        assert len(secrets) >= 6
        wire = json.dumps(model_requests(), ensure_ascii=False)
        stored = " ".join(c["payload"]["summary"] for c in chat.compactions())
        assert all(secret not in wire and secret not in stored for secret in secrets)
        assert sum("<conversation>" in json.dumps(r["messages"]) for r in model_requests()) >= 3


async def test_a_manual_compaction_writes_one_event_and_a_second_request_at_once_answers_with_it():
    async with Visitor(HOST) as v, LongChat.open(v) as chat:
        for n in range(10):
            await chat.say(talk(n))
        async with httpx.AsyncClient() as http:
            http.cookies.update(v.http.cookies)
            body = {"keep_recent_tokens": 150}
            headers = {"X-CSRFToken": v.csrf}
            first, second = await asyncio.gather(
                *(http.post(f"{HOST}/c/{chat.chat}/compact", json=body, headers=headers) for _ in range(2))
            )
        assert first.status_code == second.status_code == 200
        assert first.json()["compacted"] and first.json() == second.json()
        log = await v.log(chat.chat)
        manual = [e for e in log if e["type"] == "compaction" and e["payload"]["trigger"] == "manual"]
        assert len(manual) == 1 and manual[0]["seq"] == first.json()["seq"]


async def test_only_the_owner_compacts_and_a_stranger_finds_no_chat():
    async with Visitor(HOST) as owner, Visitor(HOST) as stranger:
        chat = await owner.new_chat()
        await owner.send(chat, "hello")
        assert (await stranger.post(f"/c/{chat}/compact")).status_code == 404
        assert (await owner.post(f"/c/{chat}/compact")).status_code == 200


async def test_a_summary_that_fails_leaves_the_turn_answered_and_the_fallback_recorded():
    async with httpx.AsyncClient() as http:
        await http.post(f"{FAKE_MODEL}/v1/_config", json={"summary_mode": "fail"})
    async with Visitor(HOST) as v, LongChat.open(v) as chat:
        for n in range(20):
            await chat.say(talk(n))
        fallbacks = [c for c in chat.compactions() if c["payload"]["trigger"] == "fallback"]
        assert fallbacks and all(c["payload"]["model"] == "" for c in fallbacks)
        assert "HTTP 500" in fallbacks[0]["payload"]["reason"]
        finished = [e for e in chat.events if e["type"] == "turn.finished"]
        assert len(finished) == 21 and all(e["payload"]["reason"] == "completed" for e in finished)
        assert not [e for e in chat.events if e["type"] == "notice"]


async def test_a_summary_that_forgets_facts_is_asked_again_and_then_completed_by_rule():
    async with httpx.AsyncClient() as http:
        await http.post(f"{FAKE_MODEL}/v1/_config", json={"summary_mode": "forgetful"})
    async with Visitor(HOST) as v, LongChat.open(v) as chat:
        await chat.say("airtime 700 to 07031234567 on mtn")
        await chat.decline(chat.cards()[-1])
        await chat.say("Send 5k to Ada Okafor, GTBank 0123456789 when you are ready")
        for n in range(20):
            await chat.say(talk(n))
        compactions = chat.compactions()
        assert compactions and compactions[0]["payload"]["verified"] == "block"
        summary = compactions[0]["payload"]["summary"]
        assert (
            "Facts recorded mechanically" in summary and "07031234567" in summary and "0123456789" in summary
        )
        assert "₦700" in summary and ": declined" in summary


async def test_a_prompt_the_endpoint_refuses_as_too_long_is_trimmed_and_the_turn_answered():
    """The scripted endpoint refuses a request of more than 14,500 characters as the Bedrock one does, with
    status 200 and an error event. The tool definitions alone are about 10,000 of them."""
    async with httpx.AsyncClient() as http:
        await http.post(f"{FAKE_MODEL}/v1/_config", json={"refuse_over_chars": 14500})
    async with Visitor(HOST) as v, LongChat.open(v) as chat:
        for n in range(8):
            await chat.say(talk(n))
        squeezes = [c for c in chat.compactions() if "too long" in c["payload"]["reason"]]
        assert squeezes and all(c["payload"]["trigger"] == "fallback" for c in squeezes)
        finished = [e for e in chat.events if e["type"] == "turn.finished"]
        assert len(finished) == 9 and all(e["payload"]["reason"] == "completed" for e in finished)
        assert not [e for e in chat.events if e["type"] == "notice"]
