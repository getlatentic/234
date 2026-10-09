# SPDX-License-Identifier: AGPL-3.0-or-later
"""A research run's chat: an ordinary chat core that reads and writes a report, with a wall-clock limit.

It is a chat of its own (its row has `parent`, and chat_research says how the run stands), so its log, its
watchdog and its tool rules are the ones every chat has. It may use the sources and the web, nothing else, and
it posts its report to the chat it researches for when its turn ends or its time is up."""

from collections.abc import Awaitable, Callable
from typing import Any

from .. import fold, kinds, scope
from ..chat_core import ChatCore
from ..eventlog import Event
from ..runner import TurnRunner
from .prompt import SYSTEM
from .store import CONNECTORS, DONE, FAILED, RUNNING, TIMED_OUT, ResearchStore

REPORT_CHARS = 6000
KEPT_NOTICES = ("Source:", "Not in the sources I read")
Reporter = Callable[[str, str, str], Awaitable[None]]
"""Posts a report: (the chat it is for, the run, the text). A report posted again adds nothing."""

NOTHING = "The research found nothing to report."
TIMED = "The research ran out of time before it finished."
BROKE = "The research could not finish."


class ResearchCore(ChatCore):
    def __init__(self, *args: Any, store: ResearchStore, reporter: Reporter, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._store, self._reporter = store, reporter

    async def begin(self, question: str) -> dict[str, Any]:
        return await self.submit(kinds.USER, question)

    async def new_runner(self) -> TurnRunner:
        return TurnRunner(
            self.log, self._db, self._model, self._hub, self._settings, await self._owner_of_chat(),
            self._clock, servers=scope.servers_of(CONNECTORS), metrics=self._metrics, system=SYSTEM,
            notes=False,
        )  # fmt: skip

    async def _settled(self) -> None:
        events = await self.log.context()
        if fold.open_turn(events) is None and any(e.type == kinds.TURN_FINISHED for e in events):
            await self.report(DONE)

    async def on_alarm(self) -> None:
        run = await self._store.get(self.chat_id)
        if run and run["status"] == RUNNING and self._clock() >= run["deadline_at"]:
            await self.cancel()
            await self.report(TIMED_OUT)
            return
        await super().on_alarm()

    async def report(self, status: str) -> None:
        """Posts the report once and marks the run finished. The post comes first, and the chat it is for
        takes a report once, so a restart between the two posts nothing twice."""
        run = await self._store.get(self.chat_id)
        if run is None or run["status"] != RUNNING:
            return
        await self._reporter(run["parent"], self.chat_id, report_text(await self.log.context(), status))
        await self._store.close(self.chat_id, status)
        await self._alarms.disarm()


def _reply(events: list[Event]) -> str:
    said = (e.payload.get("text", "").strip() for e in reversed(events) if e.type == kinds.ASSISTANT)
    return next((text for text in said if text), "")


def report_text(events: list[Event], status: str) -> str:
    """The run's last words and the source lines the host wrote after them, clipped."""
    said = _reply(events)
    lines = [
        e.payload["text"]
        for e in events
        if e.type == kinds.NOTICE and e.payload["text"].startswith(KEPT_NOTICES)
    ]
    lead = {DONE: "", TIMED_OUT: TIMED, FAILED: BROKE}[status]
    body = "\n".join(
        part for part in (lead, said or (NOTHING if status == DONE else ""), *dict.fromkeys(lines)) if part
    )
    return body[:REPORT_CHARS]
