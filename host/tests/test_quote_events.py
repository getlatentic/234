# SPDX-License-Identifier: AGPL-3.0-or-later
"""The chat follows how its quotes end: a quote's card subscribes the chat's owner to quote.finished, and an
ending refreshes the card and is put to the model, which answers it, once however often it is delivered."""

import pytest

from turns import kinds, messages
from turns.ledger_owner import ledger_owner

from .support import FakeHub, ScriptedModel, quote_result, tool_call
from .test_chat_core import MAKE, Core

EVENTS = {"public_base_url": "https://234.example", "events_secret": "dummy-events-secret"}


@pytest.fixture
def core(chat, sql, clock):
    def make(model, hub=None, **changes):
        return Core(chat, sql, clock, model, hub, **changes)

    return make


async def quote_card(core, hub=None, **settings):
    c = core(
        ScriptedModel(("", [tool_call(MAKE, {})]), "Check the card.", "Your airtime was delivered."),
        hub,
        **settings,
    )
    await c.core.submit(kinds.USER, "buy airtime")
    await c.settle()
    return c


async def test_a_quote_card_subscribes_the_chats_owner_to_how_that_quote_ends(core, chat):
    c = await quote_card(core, **EVENTS)
    (server, params, owner) = c.hub.subscriptions[0]
    assert server == "s" and params["arguments"] == {"quote_id": "qt-1"} and owner == ledger_owner(chat.owner)
    assert params["delivery"]["url"] == "https://234.example/hooks/events"


async def test_without_the_settings_or_with_a_refusal_the_card_is_kept_and_polls(core):
    assert (await quote_card(core)).hub.subscriptions == []
    hub = FakeHub({MAKE: quote_result()})
    hub.refuse_subscriptions = True
    c = await quote_card(core, hub, **EVENTS)
    assert kinds.CARD in await c.types()


async def test_an_ending_refreshes_the_card_and_the_model_answers_it_once(core):
    c = await quote_card(core, **EVENTS)

    async def call_app_tool(server, name, arguments, owner):
        return quote_result("succeeded", token=None)

    c.hub.call_app_tool = call_app_tool
    assert (
        await c.core.quote_ended("qt-1", "evt_qt-1_settled", "Quote qt-1 (₦500, MTN) paid and done.") is True
    )
    await c.settle()
    assert (
        await c.core.quote_ended("qt-1", "evt_qt-1_settled", "Quote qt-1 (₦500, MTN) paid and done.") is False
    )
    await c.settle()
    log = await c.core.log.read()
    assert [e.type for e in log].count(kinds.EVENT) == 1
    assert any(e.type == kinds.CARD_STATE for e in log)
    assert log[-1].type == kinds.TURN_FINISHED
    assert any(e.type == kinds.ASSISTANT and "delivered" in e.payload.get("text", "") for e in log)


async def test_the_model_reads_an_ending_as_an_event_not_as_the_person(core):
    c = await quote_card(core, **EVENTS)

    async def call_app_tool(server, name, arguments, owner):
        return quote_result("succeeded", token=None)

    c.hub.call_app_tool = call_app_tool
    await c.core.quote_ended("qt-1", "evt_1", "Quote qt-1 (₦500, MTN) paid and done.")
    await c.settle()
    rendered = messages.render(await c.core.log.read(), "system")
    assert {"role": "user", "content": "[event] Quote qt-1 (₦500, MTN) paid and done."} in rendered
