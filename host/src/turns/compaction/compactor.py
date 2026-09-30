# SPDX-License-Identifier: AGPL-3.0-or-later
"""Compaction: when the model's context has grown too large, the older part of the conversation is replaced
in the model's view by a summary. The log is never rewritten: the compaction is one more event, and the
context is a fold of the log that starts from the latest one (messages.py).

It runs before a model call, so a person whose context is over the threshold waits for one more model
call, once every few tens of turns. A summary that cannot be had never fails the turn: the context is
trimmed by rule instead and the compaction is recorded as a fallback, with the reason.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from .. import kinds, messages
from ..eventlog import Event, EventLog
from ..model import Model
from ..settings import Settings
from ..tokens import corrected, ratio_of, request_tokens, text_tokens
from .facts import FACTS_HEADING, facts_block
from .plan import MIN_COVERED_TOKENS, Cut, choose_cut, trim
from .summary import Summary, SummaryFailed, summarise
from .transcript import transcript

logger = logging.getLogger(__name__)

TARGET_OF_THRESHOLD = 0.75
SQUEEZE_TARGET_OF_USED = 0.5
HARD_LIMIT_OF_WINDOW = 0.9
BLOCK_RESERVE_TOKENS = 800

Permit = Callable[[], Awaitable[bool]]


def identity(first: int, last: int, pruned_before: int) -> str:
    """What a compaction is, apart from when it is written: the range it covers and where stubbing stops."""
    return f"compaction:{first}-{last}:{pruned_before}"


class Compactor:
    def __init__(
        self, log: EventLog, model: Model, settings: Settings, clock: Callable[[], int], permit: Permit
    ) -> None:
        self._log, self._model, self._settings, self._clock, self._permit = (
            log,
            model,
            settings,
            clock,
            permit,
        )
        self._lock = asyncio.Lock()
        self._closed = False

    def close(self) -> None:
        """No compaction is written from now on: the chat is being deleted."""
        self._closed = True

    def _used(self, events: list[Event], system: str, tools: list[dict[str, Any]]) -> int:
        return corrected(request_tokens(messages.render(events, system), tools), ratio_of(events))

    async def before_round(self, events: list[Event], system: str, tools: list[dict[str, Any]]) -> bool:
        """Compacts when the next request is over the threshold; True when the log changed."""
        if self._used(events, system, tools) <= self._settings.compact_threshold_tokens:
            return False
        async with self._lock:
            events = await self._log.context()
            if self._used(events, system, tools) <= self._settings.compact_threshold_tokens:
                return False
            return (
                await self._compact(
                    events, kinds.TRIGGER_AUTO, self._settings.keep_recent_tokens, system, tools
                )
                is not None
            )

    async def squeeze(self, system: str, tools: list[dict[str, Any]]) -> bool:
        """The endpoint said the request did not fit: trim well below what compaction aims for, with no model
        call. True when the log changed."""
        async with self._lock:
            events = await self._log.context()
            keep = self._settings.keep_recent_tokens // 2
            return (
                await self._trimmed(
                    events,
                    "the endpoint refused the context as too long",
                    keep,
                    system,
                    tools,
                    self._clock(),
                    int(self._used(events, system, tools) * SQUEEZE_TARGET_OF_USED),
                )
                is not None
            )

    async def manual(
        self, system: str, tools: list[dict[str, Any]], keep_recent_tokens: int | None = None
    ) -> Event | None:
        """Compacts now, whatever the size. Two requests that arrive together make one compaction: the second
        finds that one was written after it arrived, and answers with that one."""
        seen = await self._log.newest_of_type(kinds.COMPACTION)
        async with self._lock:
            if (newest := await self._log.newest_of_type(kinds.COMPACTION)) != seen:
                return next(e for e in await self._log.context() if e.seq == newest)
            events = await self._log.context()
            keep = self._settings.keep_recent_tokens if keep_recent_tokens is None else keep_recent_tokens
            return await self._compact(events, kinds.TRIGGER_MANUAL, keep, system, tools)

    async def _compact(
        self, events: list[Event], trigger: str, keep: int, system: str, tools: list[dict[str, Any]]
    ) -> Event | None:
        started, now = self._clock(), self._clock()
        ratio = ratio_of(events)
        least = max(MIN_COVERED_TOKENS, keep // 2) if trigger == kinds.TRIGGER_AUTO else MIN_COVERED_TOKENS
        cut = choose_cut(events, keep, now, ratio, least)
        if cut is None:
            over_hard_limit = (
                self._used(events, system, tools)
                > self._settings.context_window_tokens * HARD_LIMIT_OF_WINDOW
            )
            if trigger != kinds.TRIGGER_AUTO or not over_hard_limit:
                return None
            return await self._trimmed(events, "nothing could be summarised", keep, system, tools, started)
        try:
            return await self._summarised(events, cut, trigger, system, tools, started)
        except Exception as failed:
            reason = (
                failed.reason
                if isinstance(failed, SummaryFailed)
                else f"{type(failed).__name__} while summarising"
            )
            logger.warning("Compaction of chat %s fell back to trimming: %s", self._log.chat_id, reason)
            return await self._trimmed(events, reason, keep, system, tools, started)

    async def _summarised(
        self,
        events: list[Event],
        cut: Cut,
        trigger: str,
        system: str,
        tools: list[dict[str, Any]],
        started: int,
    ) -> Event | None:
        if not await self._permit():
            raise SummaryFailed("the model budget is used up")
        previous = messages.latest_compaction(events)
        covered = [e for e in events if cut.first <= e.seq <= cut.last]
        written = await summarise(
            self._model,
            previous.summary if previous else "",
            transcript(covered),
            events,
            cut.last,
            self._clock(),
            self._settings.compaction_timeout_seconds,
        )
        return await self._record(
            events, cut.first, cut.last, written, trigger, "", 0, system, tools, started
        )

    async def _trimmed(
        self,
        events: list[Event],
        reason: str,
        keep: int,
        system: str,
        tools: list[dict[str, Any]],
        started: int,
        target_tokens: int | None = None,
    ) -> Event | None:
        """No summary: stub the old bulky results, and drop the oldest messages as far as it takes."""
        now, ratio = self._clock(), ratio_of(events)
        previous = messages.latest_compaction(events)
        carried = previous.summary if previous else ""
        reserved = corrected(request_tokens([{"role": "system", "content": system}], tools), ratio)
        reserved += text_tokens(carried) + min(
            BLOCK_RESERVE_TOKENS, self._settings.compact_threshold_tokens // 10
        )
        plan = trim(
            events,
            reserved,
            target_tokens or int(self._settings.compact_threshold_tokens * TARGET_OF_THRESHOLD),
            keep,
            now,
            ratio,
        )
        cut = plan.cut
        if cut is None and plan.pruned_before == (previous.pruned_before if previous else 0):
            return None
        first, last = (
            (cut.first, cut.last)
            if cut
            else ((previous.cut if previous else 1), (previous.cut if previous else 1) - 1)
        )
        summary = carried
        if cut:
            summary = carried.split(FACTS_HEADING)[0].rstrip()
            summary = f"{summary}\n\n{facts_block(events, last, now)}".strip()
        return await self._record(
            events,
            first,
            last,
            Summary(summary, "trimmed", 0),
            kinds.TRIGGER_FALLBACK,
            reason,
            plan.pruned_before,
            system,
            tools,
            started,
        )

    async def _record(
        self,
        events: list[Event],
        first: int,
        last: int,
        written: Summary,
        trigger: str,
        reason: str,
        pruned_before: int,
        system: str,
        tools: list[dict[str, Any]],
        started: int,
    ) -> Event | None:
        """Appends the compaction, unless one was written since `events` were read or the chat is going."""
        if self._closed:
            return None
        payload = {
            "covers": {"first": first, "last": last},
            "summary": written.text,
            "pruned_before": pruned_before,
            "trigger": trigger,
            "reason": reason,
            "verified": written.verified,
            "model": "" if trigger == kinds.TRIGGER_FALLBACK else self._settings.llm_model,
            "calls": written.calls,
        }
        provisional = Event(0, kinds.COMPACTION, None, None, payload, 0)
        tokens = {
            "before": self._used(events, system, tools),
            "after": self._used([*events, provisional], system, tools),
        }
        newest = max((e.seq for e in events if e.type == kinds.COMPACTION), default=0)
        payload |= {"tokens": tokens, "ms": self._clock() - started}
        return await self._log.append_next_of_type(
            kinds.COMPACTION, payload, ref=identity(first, last, pruned_before), newest=newest
        )
