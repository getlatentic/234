# SPDX-License-Identifier: AGPL-3.0-or-later
"""The doubles and the rig that the compaction tests share: a model that tells the summariser's calls from the
turn's own, and a runner over a real log with a small context window."""

import asyncio
from collections.abc import Callable
from typing import Any

from turns import kinds
from turns.compaction.compactor import Compactor
from turns.eventlog import Event, EventLog
from turns.model import Finished, TextDelta
from turns.runner import TurnRunner
from turns.settings import Settings

from . import scripted_summary
from .support import FakeHub, ScriptedModel, quote_result


class RoutedModel:
    """Answers the summariser's calls from a scripted summariser (`mode`) and everything else from `turn`.

    `mode` may also be an exception (raised as the model client would) or a callable that writes the summary
    from the request; `slow` holds the answer back that many seconds."""

    def __init__(self, turn: Any = None, mode: Any = "faithful", slow: float = 0.0) -> None:
        self.turn = turn or ScriptedModel(*(["Fine."] * 500))
        self.mode, self.slow = mode, slow
        self.summaries: list[list[dict[str, Any]]] = []
        self.sent: list[list[dict[str, Any]]] = []

    async def stream(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]):
        if not scripted_summary.is_summary_request(messages):
            self.sent.append(messages)
            async for piece in self.turn.stream(messages, tools):
                yield piece
            return
        self.summaries.append(messages)
        if self.slow:
            await asyncio.sleep(self.slow)
        if isinstance(self.mode, Exception):
            raise self.mode
        attempt = 1 if scripted_summary.LEFT_OUT in messages[-1]["content"] else 0
        text = (
            self.mode(messages)
            if callable(self.mode)
            else scripted_summary.write(messages, self.mode, attempt)
        )
        yield TextDelta(text)
        yield Finished("stop", [])


def small(**changes: Any) -> Settings:
    """A context window of 2,000 tokens that compacts at 1,000 and keeps about 300 verbatim."""
    base = {
        "mcp_url": "http://x",
        "llm_base_url": "http://m",
        "llm_api_key": "k",
        "context_window_tokens": 2000,
        "compact_at": 0.5,
        "keep_recent_tokens": 300,
    }
    return Settings(**(base | changes))


def filler(tokens: int) -> str:
    return "a" * (4 * tokens)


class Rig:
    """A chat's log in SQLite, a runner over it and a compactor of its own to call directly."""

    def __init__(self, chat, sql, clock, model, hub=None, **changes):
        self.model = model
        self.settings = small(**changes)
        self.log = EventLog(sql, chat.id, clock)
        self.hub = hub or FakeHub({"s__make": quote_result()})
        counter = iter(range(1, 100000))
        self.runner = TurnRunner(
            self.log, sql, model, self.hub, self.settings, "v:a", clock, ids=lambda: f"id{next(counter)}"
        )
        self.compactor = Compactor(self.log, model, self.settings, clock, self._permit)
        self._permitted: Callable[[], bool] = lambda: True

    async def _permit(self) -> bool:
        return self._permitted()

    def deny_summaries(self) -> None:
        self._permitted = lambda: False

    async def say(self, text: str) -> None:
        await self.log.append(kinds.USER, {"text": text})
        await self.runner.run()

    async def chat(self, turns: int, each: int = 120, prefix: str = "talk") -> None:
        """Turns written straight into the log (the runner is not run, so nothing compacts on the way)."""
        for n in range(turns):
            user = await self.log.append(
                kinds.USER, {"text": f"{prefix} {n} {filler(each)}"[: 4 * each]}, task="t"
            )
            await self.log.append(kinds.TURN_STARTED, {"task": "t"}, task="t")
            await self.log.append(
                kinds.ASSISTANT,
                {"message": f"{prefix}{n}", "text": "Fine. ", "finish_reason": "stop", "upto": user.seq},
                task="t",
            )
            await self.log.append(kinds.TURN_FINISHED, {"task": "t", "reason": "completed"}, task="t")

    async def call(self, said: str, call_id: str, result: str | None, text: str = "") -> Event:
        """A message, the reply that answers it with a tool call and, when given, the result; the reply."""
        user = await self.log.append(kinds.USER, {"text": said}, task="t")
        call = {"id": call_id, "name": "s__make", "arguments": "{}"}
        reply = await self.log.append(
            kinds.ASSISTANT,
            {
                "message": f"m{call_id}",
                "text": text,
                "finish_reason": "tool_calls",
                "upto": user.seq,
                "tool_calls": [call],
            },
            task="t",
        )
        if result is not None:
            payload = {
                "call_id": call_id,
                "server": "s",
                "tool": "make",
                "arguments": {},
                "result_text": result,
            }
            await self.log.append(kinds.TOOL, payload | {"is_error": False}, task="t")
        return reply

    async def compactions(self):
        return [e for e in await self.log.read(limit=10000) if e.type == kinds.COMPACTION]

    async def events(self):
        return await self.log.context()


async def seed_quotes(rig: Rig, specs: list[tuple[str, int, str]]) -> None:
    """Quotes made and settled in the log as a card call would leave them: the card, then its states."""
    from .log_builder import quote_view

    for ref, kobo, phase in specs:
        await rig.log.append(
            kinds.CARD,
            {"server": "s", "tool": "make", "resource_uri": "ui://s/card.html",
             "result": quote_view(ref, "awaiting_approval", kobo, "airtime to 0703 123 4567")},
            ref=ref,
        )  # fmt: skip
        if phase != "awaiting_approval":
            await rig.log.append(
                kinds.CARD_STATE,
                {"result": quote_view(ref, phase, kobo, "airtime to 0703 123 4567")},
                ref=ref,
            )
