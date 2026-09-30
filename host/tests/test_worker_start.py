# SPDX-License-Identifier: AGPL-3.0-or-later
"""The first message of a chat, against the running Worker and its D1: the chat is made once, whatever
the number of messages that arrive for its id at the same moment, and a refused message makes none."""

import asyncio
import re

import pytest

from .worker_client import Visitor, finished, reset_budget, until

pytestmark = pytest.mark.worker
CHATS = re.compile(r'href="/c/([0-9a-f]{32})/"')


@pytest.fixture(autouse=True)
async def fresh_budget():
    await reset_budget()


async def chats_listed(visitor: Visitor) -> set[str]:
    return set(CHATS.findall((await visitor.http.get("/")).text))


async def race(rounds: int, messages: int) -> None:
    """Each round is a visitor whose page sends `messages` first messages for its one new chat at once."""
    for _ in range(rounds):
        async with Visitor() as v:
            chat = await v.new_chat()
            answers = await asyncio.gather(*[v.send(chat, f"echo: message {n}") for n in range(messages)])
            assert [a.status_code for a in answers] == [200] * messages
            assert await chats_listed(v) == {chat}


async def test_first_messages_at_once_make_one_chat():
    """D1 reports a lost insert as its own exception, which once failed one race in twenty."""
    await race(rounds=25, messages=4)


async def test_first_messages_at_once_are_all_kept():
    async with Visitor() as v:
        chat = await v.new_chat()
        await asyncio.gather(*[v.send(chat, f"echo: message {n}") for n in range(8)])
        events = await until(v.sse(chat), lambda e: finished(e) and e["seq"] > 8, timeout=30)
        assert sorted(e["payload"]["text"] for e in events if e["type"] == "user") == sorted(
            f"echo: message {n}" for n in range(8)
        )


async def test_a_refused_first_message_leaves_no_chat_and_the_next_one_still_makes_it():
    async with Visitor() as v:
        chat = await v.new_chat()
        refused = await v.send(chat, "card 4242 4242 4242 4242")
        assert refused.status_code == 422 and await chats_listed(v) == set()
        assert (await v.send(chat, "hello")).status_code == 200
        assert await chats_listed(v) == {chat}


async def test_someone_elses_chat_id_cannot_be_started_again():
    async with Visitor() as owner, Visitor() as other:
        chat = await owner.new_chat()
        await owner.send(chat, "hello")
        assert (await other.post(f"/c/{chat}/start", {"text": "hi"})).status_code == 404
