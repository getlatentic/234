# SPDX-License-Identifier: AGPL-3.0-or-later
"""Research against the running Workers (workerd Durable Objects and D1): a chat starts a run, the run is a
chat of another Durable Object that searches the fixture sources, and its report comes back to the first chat
as an event that the model answers. Run with the stack up (`pytest -m worker`)."""

import pytest

from .worker_client import Visitor, finished, reset_budget, until

pytestmark = pytest.mark.worker


@pytest.fixture(autouse=True)
async def fresh_budget():
    await reset_budget()


async def test_a_question_is_researched_on_its_own_and_the_report_comes_back_to_the_chat():
    async with Visitor() as v:
        chat = await v.new_chat()
        assert (await v.send(chat, "research how to renew a driver's licence")).status_code == 200
        first = await until(v.sse(chat), finished, timeout=60)
        (started,) = [e["payload"] for e in first if e["type"] == "tool"]
        assert (started["tool"], started["is_error"]) == ("start_research", False)
        assert started["result_text"].startswith("Started.")
        answered = [e["payload"]["text"] for e in first if e["type"] == "assistant" and e["payload"]["text"]]
        assert "researching" in answered[-1]

        seen = await until(
            v.sse(chat),
            lambda e: e["type"] == "turn.finished" and e["seq"] > first[-1]["seq"] + 1,
            timeout=120,
        )
        (report,) = [e for e in seen if e["type"] == "event" and (e["ref"] or "").startswith("research:")]
        assert "15,000 naira" in report["payload"]["text"] and "Source:" in report["payload"]["text"]
        replies = [
            e["payload"]["text"] for e in seen if e["type"] == "assistant" and e["seq"] > report["seq"]
        ]
        assert "The research found: 15,000 naira." in replies

        listed = {c["id"] for c in (await v.http.get("/api/me")).json()["chats"]}
        assert listed == {chat}
        assert (await v.http.get(f"/c/{report['ref'].removeprefix('research:')}/")).status_code == 404
