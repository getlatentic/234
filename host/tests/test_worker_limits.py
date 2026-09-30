# SPDX-License-Identifier: AGPL-3.0-or-later
"""The public-deployment guards, against the running host (local workerd and D1): the daily model cap holds
when turns arrive together, each visitor has a share of it, and the rate limiter slows one visitor.

Start the stack with `CAP=6 VISITOR_CAP=3 tools/up.sh` and run `pytest -m worker tests/test_worker_limits.py`.
"""

import asyncio

import httpx
import pytest

from .worker_client import HOST, OPS, Visitor, finished, reset_budget, until

pytestmark = pytest.mark.worker
GLOBAL_CAP = 6
VISITOR_CAP = 3


@pytest.fixture(autouse=True)
async def fresh_budget():
    await reset_budget()


async def answered(visitor: Visitor, chat: str) -> bool:
    """True when the turn was answered by the model, False when a cap said no."""
    events = await until(visitor.sse(chat), finished, timeout=30)
    return not any(e["type"] == "notice" and "budget" in e["payload"]["text"] for e in events)


async def one_turn(text: str = "hello") -> bool:
    async with Visitor() as visitor:
        chat = await visitor.new_chat()
        await visitor.send(chat, text)
        return await answered(visitor, chat)


async def test_the_daily_cap_holds_when_turns_arrive_together():
    outcomes = await asyncio.gather(*[one_turn() for _ in range(9)])
    assert outcomes.count(True) == GLOBAL_CAP, outcomes
    async with httpx.AsyncClient() as admin:
        used = (await admin.post(f"{HOST}/ops/budget/", headers=OPS, json={})).json()["used"]
    assert used == GLOBAL_CAP


async def test_a_visitor_has_a_share_of_the_day_and_others_are_not_shut_out():
    async with Visitor() as heavy:
        chat = await heavy.new_chat()
        outcomes = []
        for n in range(5):
            since = (await heavy.log(chat))[-1]["seq"] if n else 0
            await heavy.send(chat, f"hello {n}")
            events = await until(
                heavy.sse(chat, since), lambda e, since=since: finished(e) and e["seq"] > since, timeout=30
            )
            outcomes.append(
                not any(e["type"] == "notice" and "today's share" in e["payload"]["text"] for e in events)
            )
    assert outcomes == [True] * VISITOR_CAP + [False] * (5 - VISITOR_CAP)
    assert await one_turn() is True


async def test_one_visitor_is_rate_limited_after_a_burst():
    async with Visitor() as visitor:
        chat = await visitor.new_chat()
        statuses = [(await visitor.send(chat, "hello")).status_code for _ in range(16)]
    assert 429 in statuses, statuses
    assert statuses.count(200) <= 12, statuses
