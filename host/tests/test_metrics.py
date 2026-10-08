# SPDX-License-Identifier: AGPL-3.0-or-later
"""What 234 records about how it runs (turns/metrics.py, turns/health.py): a data point for each finished
turn and each tool call, and for each part of the health check; never who asked or what was said; and
recording that fails never fails the turn."""

import asyncio

import pytest

from turns import health, kinds
from turns.chat_core import ChatCore
from turns.metrics import Metrics, metrics_of
from turns.settings import Settings

from .support import FakeAlarms, FakeHub, FakeSockets, ScriptedModel, tool_call

SEND, STATUS = "s__send", "s__status"


class Sink:
    def __init__(self, broken: bool = False) -> None:
        self.points: list[tuple[str, tuple, tuple]] = []
        self.broken = broken

    def write(self, kind, blobs, doubles):
        if self.broken:
            raise RuntimeError("the binding is gone")
        self.points.append((kind, tuple(blobs), tuple(doubles)))

    def of(self, kind):
        return [(blobs, doubles) for k, blobs, doubles in self.points if k == kind]


def core(chat, sql, clock, sink, *script, **changes):
    hub = FakeHub({SEND: {"content": [{"type": "text", "text": "sent"}]}, STATUS: {"isError": True,
                   "content": [{"type": "text", "text": "no"}]}}, card_uri=None)  # fmt: skip
    hub.read_only_tools = {STATUS}
    settings = Settings(mcp_url="x", llm_base_url="m", llm_api_key="k", **changes)
    made = ChatCore(chat.id, sql, settings, ScriptedModel(*script), hub, FakeSockets(), FakeAlarms(), clock,
                    metrics=Metrics(sink))  # fmt: skip
    return made, hub


async def settle(made):
    while made.running:
        await asyncio.sleep(0)
        await made._driver


async def test_a_finished_turn_and_each_of_its_tool_calls_are_one_data_point_each(chat, sql, clock):
    sink = Sink()
    made, _ = core(
        chat, sql, clock, sink, ("", [tool_call(SEND, {}, "c1"), tool_call(STATUS, {}, "c2")]), "Done."
    )
    await made.submit(kinds.USER, "send it and check")
    await settle(made)
    ((blobs, doubles),) = sink.of("turn")
    assert blobs == ("completed", "") and doubles[1] == 2, "how it ended, and its two model rounds"
    assert [b for b, _ in sink.of("tool")] == [("s", "send", "ok"), ("s", "status", "error")]


async def test_a_data_point_names_no_owner_chat_or_words(chat, sql, clock):
    sink = Sink()
    made, _ = core(chat, sql, clock, sink, ("", [tool_call(SEND, {"to": "Ada"}, "c1")]), "Sent to Ada.")
    await made.submit(kinds.USER, "send ₦5,000 to Ada")
    await settle(made)
    written = repr(sink.points)
    owner = (await sql.row("SELECT owner FROM chat_chat WHERE id = ?", chat.id))["owner"]
    assert chat.id not in written and owner not in written and "Ada" not in written and "5,000" not in written


async def test_a_metrics_binding_that_fails_never_fails_the_turn(chat, sql, clock):
    made, _ = core(chat, sql, clock, Sink(broken=True), ("", [tool_call(SEND, {}, "c1")]), "Sent.")
    await made.submit(kinds.USER, "send it")
    await settle(made)
    events = await made.log.read()
    assert [e.payload["result_text"] for e in events if e.type == kinds.TOOL] == ["sent"]
    finished = [e for e in events if e.type == kinds.TURN_FINISHED]
    assert finished[0].payload["reason"] == kinds.COMPLETED


async def test_a_turn_given_up_records_why(chat, sql, clock):
    sink = Sink()
    made, _ = core(chat, sql, clock, sink, "never reached")
    log = made.log
    await log.append(kinds.USER, {"text": "go"}, task="t1")
    await log.append(kinds.TURN_STARTED, {"task": "t1", "trigger": 1}, task="t1")
    clock.advance(301)
    await made.on_alarm()
    await settle(made)
    ((blobs, doubles),) = sink.of("turn")
    assert blobs == ("failed", kinds.NO_PROGRESS) and doubles[0] >= 301_000


def test_without_a_binding_nothing_is_recorded():
    class Env:
        pass

    metrics_of(Env()).turn("completed", "", 1, 10, 0, 0)


async def test_each_part_of_the_health_check_is_a_data_point_and_a_failure_is_not_an_exception(monkeypatch):
    monkeypatch.setattr(health, "DEADLINE_SECONDS", 0.05)
    sink = Sink()

    async def fine():
        return None

    async def down():
        raise ConnectionError("no")

    async def stuck():
        await asyncio.sleep(1)

    passed = await health.run_checks(
        {"database": fine, "airtime": down, "chats": stuck}, Metrics(sink), lambda: 0.0
    )
    assert passed == {"database": True, "airtime": False, "chats": False}
    assert [b for b, _ in sink.of("health")] == [
        ("database", "ok"),
        ("airtime", "failed"),
        ("chats", "failed"),
    ]


@pytest.mark.parametrize("reply", [{"jsonrpc": "2.0", "id": 2, "result": {}}])
async def test_the_connector_check_is_mcps_own_ping(reply):
    import json

    import httpx

    from turns.hub import Hub

    sent = []

    def answer(request):
        body = json.loads(request.content)
        sent.append(body.get("method"))
        if body.get("method") == "initialize":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {}})
        if "id" not in body:
            return httpx.Response(202)
        return httpx.Response(200, json={**reply, "id": body["id"]})

    hub = Hub({"airtime": "http://a/mcp"}, httpx.AsyncClient(transport=httpx.MockTransport(answer)))
    await hub.ping("airtime")
    assert sent[-1] == "ping" and "tools/call" not in sent
