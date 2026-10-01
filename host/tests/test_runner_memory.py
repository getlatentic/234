# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the model is sent when the person has memory: the index right after the system prompt as labelled
data, read afresh for every round, never in the log, counted when the context is measured; and nothing of
memory for anyone without an account."""

import json

import pytest

from turns import kinds, messages
from turns.eventlog import EventLog
from turns.hub import HubError
from turns.memory import NOT_AN_ACCOUNT, NOTES_LABEL
from turns.prompt import system_prompt
from turns.runner import TurnRunner
from turns.settings import Settings

from .memory_support import ACCOUNT, INDEX, VISITOR, MemoryHub, key_of
from .support import ScriptedModel, tool_call

REMEMBER = "memory__remember"


def settings(**changes) -> Settings:
    return Settings(mcp_url="http://x", llm_base_url="http://m", llm_api_key="k", **changes)


class Rig:
    def __init__(self, chat, sql, clock, owner, model, hub, **changes):
        self.log = EventLog(sql, chat.id, clock)
        self.hub, self.model = hub, model
        counter = iter(range(1, 1000))
        self.runner = TurnRunner(
            self.log, sql, model, hub, settings(**changes), owner, clock, ids=lambda: f"id{next(counter)}"
        )

    async def say(self, text="hi"):
        return await self.log.append(kinds.USER, {"text": text})


@pytest.fixture
def rig(chat, sql, clock):
    def make(owner, model, hub=None, **changes):
        return Rig(chat, sql, clock, owner, model, hub or MemoryHub(), **changes)

    return make


def tool_names(model, round=0):
    return [t["function"]["name"] for t in model.tools[round]]


class Recording(ScriptedModel):
    def __init__(self, *script):
        super().__init__(*script)
        self.tools = []

    async def stream(self, messages, tools):
        self.tools.append(tools)
        async for piece in super().stream(messages, tools):
            yield piece


async def test_an_account_is_sent_its_notes_right_after_the_system_prompt_as_labelled_data(rig):
    r = rig(ACCOUNT, Recording("Hello"))
    await r.say("what do I have")
    await r.runner.run()
    system, notes, user = r.model.sent[0]
    assert system == {"role": "system", "content": system_prompt(settings().connectors, memory=True)}
    assert notes["role"] == "user" and notes["content"].startswith(NOTES_LABEL)
    assert f"```MEMORY.md\n{INDEX}\n```" in notes["content"]
    assert user == {"role": "user", "content": "what do I have"}


async def test_an_account_is_told_how_to_use_its_notes_and_offered_the_memory_tools(rig):
    r = rig(ACCOUNT, Recording("Hello"))
    await r.say()
    await r.runner.run()
    assert "recipient_memory_id" in r.model.sent[0][0]["content"]
    assert {n for n in tool_names(r.model) if n.startswith("memory__")} == {
        "memory__recall",
        "memory__remember",
        "memory__update",
        "memory__forget",
    }


async def test_a_visitor_is_sent_no_notes_no_word_of_memory_and_no_memory_tool(rig):
    hub = MemoryHub()
    r = rig(VISITOR, Recording("Hello"), hub)
    await r.say()
    await r.runner.run()
    system, user = r.model.sent[0]
    assert user["content"] == "hi"
    assert system["content"] == system_prompt(settings().connectors)
    assert "recall" not in system["content"] and "remember" not in system["content"]
    assert not [n for n in tool_names(r.model) if n.startswith("memory__")]
    assert hub.calls == []
    assert "recipient_memory_id" not in json.dumps(r.model.tools[0])


async def test_an_account_with_no_notes_is_sent_no_notes_message(rig):
    r = rig(ACCOUNT, Recording("Hello"), MemoryHub(index=""))
    await r.say()
    await r.runner.run()
    assert [m["role"] for m in r.model.sent[0]] == ["system", "user"]


async def test_a_connector_that_does_not_answer_leaves_the_turn_going_without_notes(rig):
    hub = MemoryHub()
    hub.index_fails = HubError("down")
    r = rig(ACCOUNT, Recording("Hello"), hub)
    await r.say()
    await r.runner.run()
    assert [m["role"] for m in r.model.sent[0]] == ["system", "user"]
    finished = next(e for e in await r.log.read() if e.type == kinds.TURN_FINISHED)
    assert finished.payload["reason"] == "completed"


async def test_the_notes_are_read_again_for_every_round_of_a_turn(rig):
    hub = MemoryHub(results={"memory__recall": {"content": [{"type": "text", "text": "found"}]}})
    model = Recording(("", [tool_call("memory__recall", {"query": "mum"})]), "Done")
    r = rig(ACCOUNT, model, hub)
    await r.say("find mum")
    original = hub.call_app_tool

    async def changing(server, name, arguments, owner):
        answer = await original(server, name, arguments, owner)
        hub.index = "## Facts\n- [Changed](aaaaaaaaaaaaaaaa) — after the first round"
        return answer

    hub.call_app_tool = changing
    await r.runner.run()
    assert hub.index_calls() == 2
    first, second = (sent[1]["content"] for sent in model.sent)
    assert INDEX in first and "Changed" not in first
    assert "Changed" in second and INDEX not in second


async def test_the_index_is_asked_for_with_the_accounts_key_and_nothing_else(rig):
    hub = MemoryHub()
    r = rig(ACCOUNT, Recording("Hello"), hub)
    await r.say()
    await r.runner.run()
    assert hub.calls == [("memory", "memory_index", {})] and hub.owners == [key_of(ACCOUNT)]


async def test_the_notes_are_never_in_the_log_so_no_summary_or_page_holds_them(rig):
    r = rig(ACCOUNT, Recording("Hello"))
    await r.say()
    await r.runner.run()
    log = json.dumps([e.payload for e in await r.log.read()])
    assert "Guaranty Trust Bank" not in log and "MEMORY.md" not in log and NOTES_LABEL not in log
    plain = messages.render(await r.log.context(), "system")
    assert "Guaranty Trust Bank" not in json.dumps(plain)


async def test_the_context_is_measured_with_the_notes_in_it(rig):
    r = rig(ACCOUNT, Recording("Hello"))
    seen = []

    async def before_round(events, system, tools):
        seen.append(system)
        return False

    r.runner._compactor.before_round = before_round
    await r.say()
    await r.runner.run()
    assert INDEX in seen[0] and seen[0].startswith("You are a money assistant")


async def test_a_memory_tool_a_model_calls_without_an_account_is_refused_before_it_leaves_the_host(rig):
    hub = MemoryHub(results={REMEMBER: {"content": [{"type": "text", "text": "saved"}]}})
    model = ScriptedModel(("", [tool_call(REMEMBER, {"kind": "fact", "title": "x"})]), "Sorry")
    r = rig(VISITOR, model, hub)
    await r.say("remember")
    await r.runner.run()
    [tool] = [e for e in await r.log.read() if e.type == kinds.TOOL]
    assert tool.payload["is_error"] is True and tool.payload["result_text"] == NOT_AN_ACCOUNT
    assert hub.model_calls == [] and hub.calls == []


async def test_a_memory_tool_an_account_calls_goes_to_the_connector_for_its_key(rig):
    hub = MemoryHub(results={REMEMBER: {"content": [{"type": "text", "text": "Proposed to remember"}]}})
    model = ScriptedModel(("", [tool_call(REMEMBER, {"kind": "fact", "title": "x"})]), "Press Save.")
    r = rig(ACCOUNT, model, hub)
    await r.say("remember")
    await r.runner.run()
    assert hub.model_calls == [(REMEMBER, {"kind": "fact", "title": "x"})] and hub.owners[-1] == key_of(
        ACCOUNT
    )


async def test_signing_in_while_the_runner_lives_gives_the_next_turn_its_notes(rig):
    r = rig(VISITOR, Recording("one", "two"))
    await r.say("first")
    await r.runner.run()
    assert [m["role"] for m in r.model.sent[0]] == ["system", "user"]
    r.runner.use_owner(ACCOUNT)
    await r.say("second")
    await r.runner.run()
    assert r.model.sent[1][1]["content"].startswith(NOTES_LABEL)
    assert "memory__recall" in tool_names(r.model, 1)
