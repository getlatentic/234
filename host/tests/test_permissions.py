# SPDX-License-Identifier: AGPL-3.0-or-later
"""What a turn may be shown and call (turns/permissions.py), through the real runner: a web turn is as it
was; a turn a personal agent sent is limited, as the person's account, to its delegation token's scopes, and a
call outside them is refused with the scopes it needs, which is how a step-up starts. An agent's own owner
(not an account) pays without a scope, since it is not the person's account."""

import pytest

from turns import kinds, permissions

from .support import FakeHub, ScriptedModel, quote_result, tool_call
from .test_chat_core import Core

pytestmark = pytest.mark.django_db
ACCOUNT = "u:" + "a" * 32
AGENT_USER = "p:" + "b" * 32
TOOLS = {
    "memory__recall": {"content": [{"type": "text", "text": "Mum: GTBank"}]},
    "airtime__make": quote_result(),
}


@pytest.fixture
def chats(db):
    """Two chats each of an account and of an agent's own User, made before the async tests run."""
    from chat.models import Chat

    return {owner: [Chat.objects.create(owner=owner) for _ in range(2)] for owner in (ACCOUNT, AGENT_USER)}


class NotesHub(FakeHub):
    """Connectors whose memory index is empty, and which count the times it is read."""

    reads = 0

    async def call_app_tool(self, server, name, arguments, owner):
        self.reads += 1
        return {"structuredContent": {"index": ""}}


async def run(chat, sql, clock, call, scopes):
    hub = NotesHub(dict(TOOLS))
    model = ScriptedModel(("", [tool_call(call, {})]), "done")
    c = Core(chat, sql, clock, model, hub)
    await c.core.submit(kinds.USER, "go", scopes=scopes)
    await c.settle()
    tool = next(e for e in await c.core.log.read() if e.type == kinds.TOOL)
    return model, hub, tool.payload


async def test_a_web_turn_of_an_account_is_unlimited_and_marks_no_scope(chats, sql, clock):
    model, hub, tool = await run(chats[ACCOUNT][0], sql, clock, "memory__recall", None)
    assert hub.calls == [("memory__recall", {})] and not tool["is_error"] and hub.reads > 0
    assert permissions.USED_FIELD not in tool and permissions.MISSING_FIELD not in tool
    assert model.offered[0] == ["memory__recall", "airtime__make"]


async def test_an_agents_turn_without_the_scope_is_refused_with_the_scope_it_needs(chats, sql, clock):
    model, hub, tool = await run(chats[ACCOUNT][0], sql, clock, "memory__recall", ["payments"])
    assert hub.calls == [] and tool["is_error"] and tool[permissions.MISSING_FIELD] == ["memory:read"]
    assert hub.reads == 0, "no notes without memory:read"
    assert "memory:read" in tool["result_text"]
    assert "memory__recall" in model.offered[0], "shown, so that asking for it is a step-up"


async def test_an_agents_turn_with_the_scope_runs_and_records_the_scope_it_used(chats, sql, clock):
    _, hub, tool = await run(chats[ACCOUNT][0], sql, clock, "memory__recall", ["memory:read"])
    assert hub.calls == [("memory__recall", {})] and tool[permissions.USED_FIELD] == "memory:read"
    _, hub, tool = await run(chats[ACCOUNT][1], sql, clock, "airtime__make", ["memory:read"])
    assert hub.calls == [] and tool[permissions.MISSING_FIELD] == ["payments"]


async def test_an_agents_own_user_pays_without_a_scope_but_reads_no_memory(chats, sql, clock):
    _, hub, tool = await run(chats[AGENT_USER][0], sql, clock, "airtime__make", [])
    assert hub.calls == [("airtime__make", {})] and permissions.USED_FIELD not in tool
    _, hub, tool = await run(chats[AGENT_USER][1], sql, clock, "memory__recall", [])
    assert hub.calls == [] and tool[permissions.MISSING_FIELD] == ["memory:read"]


def test_the_notes_are_read_only_with_memory_read_and_the_prompt_says_how_memory_is_reached():
    assert permissions.Permissions(ACCOUNT).reads_notes
    assert not permissions.Permissions(ACCOUNT, scopes=frozenset({"payments"})).reads_notes
    assert permissions.Permissions(ACCOUNT, scopes=frozenset({"memory:read"})).reads_notes
    assert not permissions.Permissions(AGENT_USER, scopes=frozenset({"memory:read"})).reads_notes
    assert not permissions.Permissions("v:" + "c" * 32).memory_tools


def test_a_brand_offers_the_scopes_of_its_connectors():
    assert list(permissions.scopes_of(["food-order"])) == ["payments"]
    assert list(permissions.scopes_of(["memory"])) == ["memory:read", "memory:write"]
    assert list(permissions.scopes_of(["memory", "airtime"])) == ["memory:read", "memory:write", "payments"]
