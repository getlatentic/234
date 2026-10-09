# SPDX-License-Identifier: AGPL-3.0-or-later
"""The `research` connector, served by the host itself: one tool, `start_research`, that hands a question to a
run of its own and answers at once. The report comes back to the chat as an event (ChatCore.research_done).

A chat has one run at a time, and a person starts a few a day: a run takes many model calls."""

from collections.abc import Callable
from typing import Any, Protocol

import httpx

from .. import trace
from ..hub import HubError
from ..settings import Settings
from .store import ResearchStore

SERVER = "research"
QUESTION_CHARS = 400
STARTED = (
    "Started. Tell the person in one sentence that you are researching it and that the report will arrive "
    "in this chat; do not wait and do not search for it yourself."
)
BUSY = "RESEARCH_BUSY: A research run is still going for this chat. Tell the person it is not finished."
LIMIT = "RESEARCH_LIMIT: The person has started as many research runs as they may today."
NO_CHAT = "RESEARCH_UNAVAILABLE: Research can only be started from a chat."
TOOLS = [
    {
        "name": "start_research",
        "description": "Researches a question that needs several searches or pages (not one fee or one page) "
        "on its own for up to a few minutes, and posts the report in this chat. Answers at once.",
        "inputSchema": {
            "type": "object",
            "properties": {"question": {"type": "string", "minLength": 5, "maxLength": QUESTION_CHARS}},
            "required": ["question"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True},
        "_meta": {"ui": {"visibility": ["model"]}},
    }
]


class Launcher(Protocol):
    async def launch(self, run: str, question: str) -> None:
        """Starts the run's chat on the question: the Durable Object of `run` begins to work."""
        ...


def _result(text: str, error: bool = False) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}], "isError": error}


class ResearchServer:
    def __init__(self, settings: Settings, store: ResearchStore, launcher: Launcher) -> None:
        self._settings, self._store, self._launcher = settings, store, launcher

    async def request(
        self, method: str, params: dict[str, Any] | None = None, owner: str | None = None, notes: bool = False
    ) -> dict[str, Any]:
        params = params or {}
        if method == "tools/list":
            return {"tools": TOOLS}
        if method == "resources/list":
            return {"resources": []}
        if method == "tools/call" and params.get("name") == "start_research":
            return await self._start(str((params.get("arguments") or {}).get("question", "")).strip())
        raise HubError(f"{method}: not offered by {SERVER}.")

    async def relay(self, *_: Any) -> httpx.Response:
        raise HubError(f"{SERVER} is not reachable from outside the host.")

    async def _start(self, question: str) -> dict[str, Any]:
        parent = trace.current().chat
        row = await self._store.parent_of_run(parent) if parent else None
        if row is None or len(question) < 5:
            return _result(NO_CHAT, error=True)
        if await self._store.running_for(parent):
            return _result(BUSY, error=True)
        if await self._store.started_today(row["owner"]) >= self._settings.researches_per_day:
            return _result(LIMIT, error=True)
        run = await self._store.start(
            parent,
            row["owner"],
            row["payer_group"],
            question[:QUESTION_CHARS],
            self._settings.research_seconds,
        )
        await self._launcher.launch(run, question[:QUESTION_CHARS])
        return _result(STARTED)


def research_server(
    settings: Settings, db: Any, clock: Callable[[], int], launcher: Launcher
) -> ResearchServer:
    return ResearchServer(settings, ResearchStore(db, clock), launcher)
