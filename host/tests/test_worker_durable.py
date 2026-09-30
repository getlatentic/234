# SPDX-License-Identifier: AGPL-3.0-or-later
"""The durability tests, against the running Workers (local workerd and local D1), once per turn runner.

They decide the runner: a turn must outlive its client, a cursor must replay a chat without a gap or a
repeat, two tabs must see one log, and two chats must not mix. Run with the stack up:
`RUNNER_URLS=do=http://localhost:8901,queue=http://localhost:8903,waituntil=http://localhost:8904 \
pytest -m worker`.
"""

import asyncio
import json
import time

import httpx
import pytest

from .worker_client import FAKE_MODEL, Visitor, finished, reset_budget, runner_urls, until

pytestmark = pytest.mark.worker
RUNNERS = runner_urls()
PAY = "Pay ₦2,500 to Demo Kitchen for lunch"


@pytest.fixture(params=list(RUNNERS))
def base(request) -> str:
    return RUNNERS[request.param]


@pytest.fixture(autouse=True)
async def fresh_budget(base):
    await reset_budget(base)


def assert_gapless(events: list[dict]) -> None:
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))


def reply_text(events: list[dict]) -> str:
    return "".join(e["payload"]["text"] for e in events if e["type"] == "assistant")


async def test_a_turn_outlives_its_client_and_a_cursor_replays_it_exactly(base):
    async with Visitor(base) as v:
        chat = await v.new_chat()
        await v.send(chat, "slow:60@0.1")
        before_kill: list[dict] = []
        async for event in v.sse(chat):
            before_kill.append(event)
            if event["seq"] >= 6:
                break
        assert not any(finished(e) for e in before_kill)

        await asyncio.sleep(9)  # the client is gone; the turn takes about 6.5 s
        started = time.monotonic()
        after = await until(v.sse(chat, last_event_id=before_kill[-1]["seq"]), finished, timeout=20)
        assert time.monotonic() - started < 3, "the turn had already finished without a client"

        everything = before_kill + after
        assert_gapless(everything)
        assert everything == await v.log(chat)
        assert reply_text(everything) == " ".join(f"word{i}" for i in range(60)) + " END"
        assert everything[-1]["payload"]["reason"] == "completed"
        assert everything[-1]["payload"]["finish_reasons"] == ["stop"]


async def test_a_pending_approval_survives_and_is_still_actionable_from_another_tab(base):
    async with Visitor(base) as v:
        chat = await v.new_chat()
        await v.send(chat, PAY)
        first = await until(v.sse(chat), finished)
        card = next(e for e in first if e["type"] == "card")
        assert first[-1]["payload"]["reason"] == "input_required"

        result = card["payload"]["result"]
        token, quote = result["_meta"]["approvalToken"], result["structuredContent"]["quote"]
        assert quote["phase"] == "awaiting_approval"

        other_tab = v.another_tab()
        async with other_tab:
            replayed = await other_tab.log(chat)
            assert replayed == first
            approved = await other_tab.post(
                f"/c/{chat}/call",
                {
                    "server": card["payload"]["server"],
                    "name": "approve_quote",
                    "arguments": {
                        "quote_id": quote["id"],
                        "approval_token": token,
                        "displayed_amount_kobo": quote["amount"]["kobo"],
                    },
                },
            )
            assert approved.status_code == 200
            assert approved.json()["structuredContent"]["quote"]["phase"] == "awaiting_checkout"

        later = await v.log(chat)
        state = [e for e in later if e["type"] == "card_state"]
        assert len(state) == 1 and state[0]["ref"] == quote["id"]
        assert state[0]["payload"]["result"]["structuredContent"]["quote"]["phase"] == "awaiting_checkout"
        assert "_meta" not in state[0]["payload"]["result"]
        assert later[: len(first)] == first
        assert_gapless(later)


async def test_the_model_is_never_shown_the_approval_token(base):
    async with Visitor(base) as v:
        chat = await v.new_chat()
        await v.send(chat, PAY)
        events = await until(v.sse(chat), finished)
        token = next(e for e in events if e["type"] == "card")["payload"]["result"]["_meta"]["approvalToken"]
        sent = httpx.get(f"{FAKE_MODEL}/v1/_requests").json()
        assert token not in json.dumps(sent)
        assert any(
            r["tool_choice"] == "auto" and r["reasoning_effort"] == "low" for r in sent if "tools" in r
        )


async def test_two_tabs_of_one_visitor_see_the_same_events_in_the_same_order(base):
    async with Visitor(base) as one:
        chat = await one.new_chat()
        async with one.another_tab() as two:
            await one.send(chat, "slow:30@0.1")
            a, b = await asyncio.gather(until(one.sse(chat), finished), until(two.sse(chat), finished))
        assert a == b
        assert_gapless(a)


async def test_two_chats_run_at_once_and_never_mix(base):
    async with Visitor(base) as one, Visitor(base) as two:
        first, second = await one.new_chat(), await two.new_chat()
        started = time.monotonic()
        await asyncio.gather(one.send(first, "slow:40@0.1"), two.send(second, "slow:25@0.1"))
        a, b = await asyncio.gather(
            until(one.sse(first), finished, timeout=30), until(two.sse(second), finished, timeout=30)
        )
        elapsed = time.monotonic() - started
        assert elapsed < 4.0 + 2.5 + 3, f"the turns ran one after the other ({elapsed:.1f} s)"
        assert reply_text(a).count("word") == 40 and reply_text(b).count("word") == 25
        assert_gapless(a)
        assert_gapless(b)
        assert {e["task"] for e in a if e["type"] != "user"}.isdisjoint({e["task"] for e in b})


async def test_a_message_sent_during_a_turn_is_answered_in_the_same_task(base):
    async with Visitor(base) as v:
        chat = await v.new_chat()
        await v.send(chat, "slow:40@0.1")
        await asyncio.sleep(1)
        assert (await v.send(chat, "hello?")).status_code == 200
        events = []
        async for event in v.sse(chat):
            events.append(event)
            if sum(finished(e) for e in events) >= 1 and sum(e["type"] == "assistant" for e in events) >= 2:
                break
        assert sum(e["type"] == "turn.started" for e in events) == 1
        assert len({e["task"] for e in events if e["type"] != "user"}) == 1
        assert_gapless(events)
