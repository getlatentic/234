# SPDX-License-Identifier: AGPL-3.0-or-later
"""A memory card in the log: the proposal is a card named by its own id, its Save is relayed to the memory
connector for the account only, the decision is pushed as the card's new state, and the token stays out of
everything the model or another client reads."""

import asyncio
import json

import pytest

from chat.models import Chat
from turns import kinds
from turns.chat_core import ChatCore
from turns.hub import HubError
from turns.memory import NOT_AN_ACCOUNT
from turns.settings import Settings

from .card_support import CardHub, listed
from .memory_support import ACCOUNT, VISITOR, key_of
from .support import FakeAlarms, FakeSockets, ScriptedModel, tool_call

CARD = "ui://memory/card.html"
REMEMBER = "memory__remember"
PROPOSAL = "0123456789abcdef"
TOKEN = "tok-confirm-secret"
NO_NOTES = {"content": [], "structuredContent": {"index": ""}}
LISTING = [
    listed("remember", CARD, "model"),
    listed("confirm_memory", CARD, "app"),
    listed("undo_memory", CARD, "app"),
    listed("list_memories", None, "app"),
]


def proposed(state: str = "pending") -> dict:
    return {
        "content": [{"type": "text", "text": "Proposed to remember the fact. Nothing is saved until Save."}],
        "structuredContent": {
            "proposal_id": PROPOSAL,
            "memory": {
                "op": "remember",
                "state": state,
                "kind": "fact",
                "title": "Lives in",
                "what": "Lives in",
            },
        },
        "_meta": {"confirmToken": TOKEN},
    }


def decided(state: str) -> dict:
    return {
        "content": [{"type": "text", "text": f"{state}: Lives in"}],
        "structuredContent": proposed(state)["structuredContent"],
    }


class MemoryCardHub(CardHub):
    async def tools(self, server: str):
        return LISTING


@pytest.fixture
def account_chat(db):
    return Chat.objects.create(owner=ACCOUNT)


@pytest.fixture
def visitor_chat(db):
    return Chat.objects.create(owner=VISITOR)


class Rig:
    def relayed(self) -> list[tuple]:
        """What the cards asked for: the index the host reads each round is not a card's call."""
        return [call for call in self.hub.app_calls if call[1] != "memory_index"]

    def __init__(self, chat, sql, clock, **app):
        app = {"confirm_memory": decided("saved"), **app}
        self.hub = MemoryCardHub({REMEMBER: proposed()}, {"memory_index": NO_NOTES, **app}, {REMEMBER: CARD})
        model = ScriptedModel(
            ("", [tool_call(REMEMBER, {"kind": "fact", "title": "Lives in"})]), "Press Save."
        )
        settings = Settings(mcp_url="x", llm_base_url="m", llm_api_key="k")
        self.core = ChatCore(chat.id, sql, settings, model, self.hub, FakeSockets(), FakeAlarms(), clock)

    async def ask(self):
        await self.core.submit(kinds.USER, "remember that I live in Yaba")
        while self.core.running:
            await asyncio.sleep(0)
            await self.core._driver

    async def events(self, type=None):
        return [e for e in await self.core.log.read() if type is None or e.type == type]


async def test_a_proposal_is_a_card_named_by_its_proposal_id_and_keeps_the_token_for_the_card(
    account_chat, sql, clock
):
    r = Rig(account_chat, sql, clock)
    await r.ask()
    [card] = await r.events(kinds.CARD)
    assert (
        card.ref == PROPOSAL and card.payload["resource_uri"] == CARD and card.payload["server"] == "memory"
    )
    assert card.payload["result"]["_meta"] == {"confirmToken": TOKEN}


async def test_the_model_reads_the_proposals_text_and_never_the_token_or_the_card_data(
    account_chat, sql, clock
):
    r = Rig(account_chat, sql, clock)
    await r.ask()
    sent = json.dumps(r.core._model.sent[-1])
    assert "Proposed to remember the fact" in sent
    assert TOKEN not in sent and PROPOSAL not in sent and "structuredContent" not in sent


async def test_save_is_relayed_to_the_memory_connector_for_the_accounts_key(account_chat, sql, clock):
    r = Rig(account_chat, sql, clock)
    await r.ask()
    done = await r.core.card_call(
        "memory", "confirm_memory", {"proposal_id": PROPOSAL, "confirm_token": TOKEN}
    )
    assert done["structuredContent"]["memory"]["state"] == "saved"
    assert r.relayed() == [("memory", "confirm_memory", {"proposal_id": PROPOSAL, "confirm_token": TOKEN})]
    assert r.hub.owners[-1] == key_of(ACCOUNT)


async def test_the_decision_is_pushed_as_the_cards_new_state_without_the_token(account_chat, sql, clock):
    r = Rig(account_chat, sql, clock)
    await r.ask()
    await r.core.card_call("memory", "confirm_memory", {"proposal_id": PROPOSAL, "confirm_token": TOKEN})
    [state] = await r.events(kinds.CARD_STATE)
    assert (
        state.ref == PROPOSAL and state.payload["result"]["structuredContent"]["memory"]["state"] == "saved"
    )
    assert TOKEN not in json.dumps(state.payload) and "_meta" not in state.payload["result"]


async def test_the_same_decision_twice_is_one_state_event(account_chat, sql, clock):
    r = Rig(account_chat, sql, clock)
    await r.ask()
    for _ in range(2):
        await r.core.card_call("memory", "confirm_memory", {"proposal_id": PROPOSAL, "confirm_token": TOKEN})
    assert len(await r.events(kinds.CARD_STATE)) == 1


async def test_a_card_cannot_call_a_tool_that_is_not_its_own(account_chat, sql, clock):
    r = Rig(account_chat, sql, clock, list_memories=decided("saved"))
    await r.ask()
    with pytest.raises(HubError, match="not a tool of this card"):
        await r.core.card_call("memory", "list_memories", {"proposal_id": PROPOSAL})
    assert r.relayed() == []


async def test_a_memory_card_of_a_chat_whose_owner_is_not_an_account_reaches_nothing(
    visitor_chat, sql, clock
):
    r = Rig(visitor_chat, sql, clock)
    payload = {"server": "memory", "tool": "remember", "resource_uri": CARD, "result": proposed()}
    await r.core.log.append(kinds.CARD, payload, ref=PROPOSAL)
    with pytest.raises(HubError, match=NOT_AN_ACCOUNT):
        await r.core.card_call("memory", "confirm_memory", {"proposal_id": PROPOSAL, "confirm_token": TOKEN})
    assert r.relayed() == []


async def test_a_visitors_model_is_not_offered_memory_so_no_memory_card_is_ever_made(
    visitor_chat, sql, clock
):
    r = Rig(visitor_chat, sql, clock)
    await r.ask()
    assert await r.events(kinds.CARD) == [] and r.hub.app_calls == []


async def test_a_card_that_names_no_proposal_or_two_is_refused(account_chat, sql, clock):
    r = Rig(account_chat, sql, clock)
    await r.ask()
    for arguments in ({"confirm_token": TOKEN}, {"proposal_id": PROPOSAL, "quote_id": "qt-1"}):
        with pytest.raises(HubError, match="names the card it is for, once"):
            await r.core.card_call("memory", "confirm_memory", arguments)
