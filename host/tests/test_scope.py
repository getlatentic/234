# SPDX-License-Identifier: AGPL-3.0-or-later
"""A chat limited to some connectors (a PACT Brand's): its model is shown their tools only, and a call to
another connector's tool is refused, whatever the model asks."""

import pytest

from turns import kinds, scope

from .support import FakeHub, ScriptedModel, quote_result, tool_call
from .test_chat_core import Core

pytestmark = pytest.mark.django_db


@pytest.fixture
def food_chat(db):
    from chat.models import Chat

    return Chat.objects.create(owner="v:a", connectors="food")


async def test_a_limited_chat_shows_and_runs_only_its_connectors_tools(food_chat, sql, clock):
    chat = food_chat
    hub = FakeHub({"food__make": quote_result(), "airtime__make": quote_result()})
    model = ScriptedModel(("", [tool_call("airtime__make", {})]), "Only food here.")
    c = Core(chat, sql, clock, model, hub)
    await c.core.submit(kinds.USER, "buy airtime")
    await c.settle()
    assert model.offered[0] == ["food__make"]
    assert hub.calls == []
    tool = next(e for e in await c.core.log.read() if e.type == kinds.TOOL)
    assert tool.payload["is_error"] and tool.payload["result_text"] == scope.OUTSIDE


async def test_a_chat_with_no_limit_shows_every_tool(chat, sql, clock):
    hub = FakeHub({"food__make": quote_result(), "airtime__make": quote_result()})
    model = ScriptedModel("hello")
    c = Core(chat, sql, clock, model, hub)
    await c.core.submit(kinds.USER, "hi")
    await c.settle()
    assert model.offered[0] == ["food__make", "airtime__make"]
