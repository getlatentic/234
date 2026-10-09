# SPDX-License-Identifier: AGPL-3.0-or-later
"""One chat's turns: the model streams, calls tools, and everything it does is appended to the log.

A turn is not held in memory. Each step reads the log, asks `next_action` what is left, does one thing
and appends the outcome, so a runner started on a half-finished turn (a restarted Durable Object)
carries on from where the log stops.
"""

import asyncio
import logging
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from . import calls as call_rules
from . import fold, kinds, logs, messages, permissions, scope, sources, trace
from .budget import add_tokens, take_model_call, tokens_used_up
from .compaction.compactor import Compactor
from .db import Db
from .eventlog import Event, EventLog
from .hub import Hub, HubError
from .memory import notes_message, read_index, with_notes
from .metrics import Metrics
from .model import ContextTooLong, Finished, Model, ModelError, TextDelta
from .prompt import system_prompt
from .settings import Settings
from .tokens import request_tokens
from .tool_calls import UNREACHABLE, ToolCalls

logger = logging.getLogger(__name__)

BUDGET_NOTICES = {
    "global": "Today's model budget is used up. Try again tomorrow.",
    "visitor": "You have used today's share of the model budget. Try again tomorrow.",
}
TOO_SLOW = "The model took too long to answer."
LENGTH_NOTICE = "The model ran out of room before it finished its reply."
ROUNDS_NOTICE = "The assistant stopped after too many tool calls in one turn."
INTERRUPTED = "The assistant was interrupted and could not continue."
STOPPED_TOOL = "Stopped by the person before it finished."
FAILED_REPLIES = ("error", "budget")
STOPPED_REPLY = "cancelled"


def new_id() -> str:
    return secrets.token_hex(8)


@dataclass
class _Streamed:
    message: str = ""
    """The id of the reply being streamed: a new one when a half reply was thrown away to ask again."""
    text: str = ""
    finished: Finished | None = None


@dataclass
class _Round:
    """A model round that has begun and has no reply in the log yet."""

    message: str
    upto: int
    streamed: _Streamed


class TurnRunner:
    def __init__(
        self,
        log: EventLog,
        db: Db,
        model: Model,
        hub: Hub,
        settings: Settings,
        owner: str,
        clock: Callable[[], int],
        ids: Callable[[], str] = new_id,
        servers: tuple[str, ...] = (),
        metrics: Metrics | None = None,
        system: str | None = None,
        notes: bool = True,
    ) -> None:
        """`servers`: the connectors this chat may use (turns/scope.py); empty is every one. `system`: the
        prompt this chat's model is given instead of the assistant's (a research run's); `notes`: whether the
        person's saved notes are read for it."""
        self._log, self._db, self._model, self._hub = log, db, model, hub
        self._settings, self._owner, self._clock, self._ids = settings, owner, clock, ids
        self._servers, self._system, self._notes = servers, system, notes
        self._permits = permissions.Permissions(owner, servers)
        self._task: str | None = None
        self._round: _Round | None = None
        self._compactor = Compactor(log, model, settings, clock, self._permit_model_call)
        self._metrics = metrics or Metrics()
        self._tools = ToolCalls(log, hub, settings, clock, self._metrics)

    async def run(self, resumed: bool = False) -> None:
        """Runs until the log has nothing left for the runner to do."""
        if resumed and not await self._resume():
            return
        while True:
            events = await self._log.context()
            turn = fold.open_turn(events)
            self._task = turn.payload["task"] if turn else None
            trace.set_task(self._task or "")
            self._permits = permissions.of(self._owner, self._servers, events)
            match fold.next_action(events):
                case fold.Idle():
                    if turn:
                        await self._finish(events, turn)
                    return
                case fold.ModelRound(driver):
                    turn = turn or await self._start(driver)
                    if self._rounds_used(events) >= self._settings.max_tool_rounds:
                        await self._stop_at_limit(events, turn)
                        return
                    await self._model_round(events)
                case fold.ToolRound(assistant, calls):
                    assert turn is not None
                    started = {e.payload["call_id"] for e in events if e.type == kinds.TOOL_STARTED}
                    for call in calls:
                        await self._tools.run(
                            call, assistant.payload["tool_calls"], self._permits, self._owner, self._task,
                            started=call["id"] in started,
                        )  # fmt: skip

    async def _start(self, driver: Event) -> Event:
        self._task = driver.task or self._ids()
        trace.set_task(self._task)
        return await self._log.append(
            kinds.TURN_STARTED, {"task": self._task, "trigger": driver.seq}, task=self._task
        )

    def _rounds_used(self, events: list[Event]) -> int:
        return sum(1 for e in events if e.type == kinds.ASSISTANT and e.task == self._task)

    async def _resume(self) -> bool:
        """False when the turn has stopped getting anywhere; otherwise it is marked resumed."""
        events = await self._log.context()
        turn = fold.open_turn(events)
        if turn is None:
            return not isinstance(fold.next_action(events), fold.Idle)
        self._task = turn.payload["task"]
        if cause := self._stalled(events, turn):
            await self._log.append(kinds.NOTICE, {"level": "error", "text": INTERRUPTED}, task=self._task)
            await self._stop_calls(INTERRUPTED)
            upto = await self._log.last_seq()
            await self._close(await self._log.context(), turn, kinds.FAILED, cause=cause, upto=upto)
            return False
        await self._abort_open_messages(turn)
        await self._log.append(kinds.TURN_RESUMED, {"task": self._task}, task=self._task)
        return True

    def _stalled(self, events: list[Event], turn: Event) -> str | None:
        """Why the turn is given up, or None. Progress is a reply or a tool result; resumes count from the
        last of them, and resumes closer together than the window count once."""
        mine = [e for e in events if e.task == self._task and e.seq >= turn.seq]
        progress = max(
            (e for e in mine if e.type in (kinds.ASSISTANT, kinds.TOOL)), key=lambda e: e.seq, default=turn
        )
        counted, last_at = 0, None
        for resumed in (e for e in mine if e.type == kinds.TURN_RESUMED and e.seq > progress.seq):
            if last_at is None or resumed.at - last_at >= self._settings.resume_window_seconds * 1000:
                counted, last_at = counted + 1, resumed.at
        if counted >= self._settings.max_idle_resumes:
            return kinds.RESUMES_EXHAUSTED
        if self._clock() - progress.at > self._settings.no_progress_seconds * 1000:
            return kinds.NO_PROGRESS
        return None

    async def _abort_open_messages(self, turn: Event) -> None:
        since = await self._log.read(after=turn.seq, limit=5000)
        answered = {e.payload["message"] for e in since if e.type == kinds.ASSISTANT}
        aborted = {e.payload["message"] for e in since if e.type == kinds.ROUND_ABORTED}
        for message in dict.fromkeys(e.payload["message"] for e in since if e.type == kinds.TEXT):
            if message not in answered | aborted:
                await self._log.append(kinds.ROUND_ABORTED, {"message": message}, task=self._task)

    async def _model_round(self, events: list[Event]) -> None:
        upto = events[-1].seq
        message = self._ids()
        began = self._clock()
        if verdict := await self._over_budget():
            await self._log.append(
                kinds.NOTICE, {"level": "info", "text": BUDGET_NOTICES[verdict]}, task=self._task
            )
            await self._reply(message, "", [], "budget", upto)
            return
        streamed = _Streamed(message)
        try:
            permits = self._permits
            system = self._system or system_prompt(
                self._servers or self._settings.offered_connectors, permits.reads_notes, permits.memory_tools
            )
            tools = permits.tools(await self._hub.model_tools())
            index = await read_index(self._hub, self._owner) if permits.reads_notes and self._notes else ""
            head = with_notes(system, index)
            notes = notes_message(index) if index else None
            events = await self._compacted(events, head, tools)
            upto = events[-1].seq
            try:
                sent = await self._asked(events, upto, streamed, system, tools, notes)
            except ContextTooLong:
                events = await self._squeezed(events, head, tools)
                upto = events[-1].seq
                sent = await self._asked(events, upto, streamed, system, tools, notes)
        except (ModelError, HubError, httpx.HTTPError) as error:
            text = str(error) if isinstance(error, ModelError | HubError) else UNREACHABLE
            await self._log.append(kinds.NOTICE, {"level": "error", "text": text}, task=self._task)
            await self._reply(streamed.message, streamed.text, [], "error", upto)
            return
        finished = streamed.finished
        assert finished is not None
        if finished.reason == "length" and not finished.tool_calls:
            await self._log.append(kinds.NOTICE, {"level": "info", "text": LENGTH_NOTICE}, task=self._task)
        message = streamed.message
        calls = call_rules.with_distinct_ids(finished.tool_calls, call_rules.used_ids(events), message)
        measured = (
            {"estimate": request_tokens(sent, tools), "usage": finished.usage} if finished.usage else {}
        )
        await self._reply(message, streamed.text, calls, finished.reason, upto, measured)
        await self._count_tokens(finished.usage, sent, tools, streamed.text)
        usage = finished.usage or {}
        logs.event(
            logger, "round", finish_reason=finished.reason, tool_calls=len(calls),
            prompt_tokens=usage.get("prompt_tokens"), completion_tokens=usage.get("completion_tokens"),
            duration_ms=self._clock() - began,
        )  # fmt: skip

    async def _asked(
        self,
        events: list[Event],
        upto: int,
        streamed: _Streamed,
        system: str,
        tools: list[dict[str, Any]],
        notes: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        """Asks the model, again after a wait when the endpoint was busy or could not be reached (at most
        `model_retries` times, the wait doubling), and the messages sent. What a failed attempt had streamed
        is thrown away first, as a restart throws it away, and the reply starts under a new id."""
        retries = self._settings.model_retries
        for attempt in range(retries + 1):
            try:
                return await self._stream_round(events, upto, streamed, system, tools, notes)
            except ModelError as error:
                if not error.transient or attempt == retries or streamed.finished is not None:
                    raise
                logger.warning("The model was not available (%s); asking again", error)
                await self._start_again(streamed)
                await asyncio.sleep(self._settings.model_retry_seconds * 2**attempt)
        raise AssertionError("unreachable")

    async def _start_again(self, streamed: _Streamed) -> None:
        if streamed.text:
            await self._log.append(kinds.ROUND_ABORTED, {"message": streamed.message}, task=self._task)
            streamed.message, streamed.text = self._ids(), ""

    async def _stream_round(
        self,
        events: list[Event],
        upto: int,
        streamed: _Streamed,
        system: str,
        tools: list[dict[str, Any]],
        notes: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Asks the model once, for the conversation as it stands; the messages sent."""
        self._round = _Round(streamed.message, upto, streamed)
        sent = messages.render(events, system, notes)
        await self._stream(streamed, streamed.message, sent, tools)
        return sent

    async def _squeezed(self, events: list[Event], system: str, tools: list[dict[str, Any]]) -> list[Event]:
        """The events after the endpoint has refused the context as too long: trimmed, or as they were."""
        logger.warning("The model refused the context as too long; trimming it")
        return await self._log.context() if await self._compactor.squeeze(system, tools) else events

    async def _compacted(self, events: list[Event], system: str, tools: list[dict[str, Any]]) -> list[Event]:
        """The events the round reads, after a compaction if the context needed one. A compaction that goes
        wrong never fails the round: it is read without it."""
        try:
            if await self._compactor.before_round(events, system, tools):
                return await self._log.context()
        except Exception:
            logger.exception("Compaction failed; the round goes on without it")
        return events

    async def _over_budget(self) -> str | None:
        """Which of today's caps (tokens, then calls) refuses a model call; None, with the call taken."""
        s = self._settings
        used_up = await tokens_used_up(
            self._db, self._owner, self._clock(), s.visitor_model_tokens_per_day, s.model_tokens_per_day
        )
        return used_up or await take_model_call(
            self._db, self._owner, self._clock(), s.visitor_model_calls_per_day, s.model_calls_per_day
        )

    async def _count_tokens(
        self, usage: dict[str, int] | None, sent: list[dict[str, Any]], tools: list[dict[str, Any]], text: str
    ) -> None:
        """What the round cost, from the endpoint's own count when it gave one, else estimated."""
        s = self._settings
        used = sum(usage.values()) if usage else request_tokens(sent, tools) + len(text) // 4
        await add_tokens(
            self._db, self._owner, self._clock(), used, s.visitor_model_tokens_per_day, s.model_tokens_per_day
        )

    async def _permit_model_call(self) -> bool:
        """A summary is a model call and counts against the same daily caps as a reply."""
        return await self._over_budget() is None

    def use_owner(self, owner: str) -> None:
        """The chat's owner as it is now: signing in moves a visitor's chats to their account while this
        runner may be alive, and the next turn is theirs."""
        self._owner = owner

    def close_compaction(self) -> None:
        self._compactor.close()

    async def compact(self, keep_recent_tokens: int | None = None) -> Event | None:
        """Compacts now, at the person's request: the event written, or None when nothing could be covered."""
        try:
            tools = scope.within(await self._hub.model_tools(), self._servers)
        except HubError, httpx.HTTPError:
            tools = []
        return await self._compactor.manual(
            system_prompt(self._servers or self._settings.offered_connectors), tools, keep_recent_tokens
        )

    async def _stream(
        self, streamed: _Streamed, message: str, sent: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> None:
        pending, flushed_at = "", self._clock()
        try:
            async with asyncio.timeout(self._settings.round_deadline_seconds):
                async for piece in self._model.stream(sent, tools):
                    if not isinstance(piece, TextDelta):
                        streamed.finished = piece
                        continue
                    streamed.text += piece.text
                    pending += piece.text
                    if self._clock() - flushed_at >= self._settings.flush_seconds * 1000:
                        await self._flush(message, pending)
                        pending, flushed_at = "", self._clock()
        except TimeoutError as error:
            raise ModelError(TOO_SLOW) from error
        finally:
            await self._flush(message, pending)

    async def _flush(self, message: str, pending: str) -> None:
        if pending:
            await self._log.append(kinds.TEXT, {"message": message, "text": pending}, task=self._task)

    async def _reply(
        self,
        message: str,
        text: str,
        calls: list[dict[str, Any]],
        reason: str,
        upto: int,
        measured: dict[str, Any] | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "message": message,
            "text": text,
            "finish_reason": reason,
            "upto": upto,
            **(measured or {}),
        }
        if calls:
            payload["tool_calls"] = calls
        await self._log.append(kinds.ASSISTANT, payload, task=self._task)
        if self._round and self._round.message == message:
            self._round = None

    async def _stop_at_limit(self, events: list[Event], turn: Event) -> None:
        await self._log.append(kinds.NOTICE, {"level": "info", "text": ROUNDS_NOTICE}, task=self._task)
        await self._close(events, turn, kinds.MAX_ROUNDS)

    async def _finish(self, events: list[Event], turn: Event) -> None:
        await self._note_sources(events)
        replies = [e for e in events if e.type == kinds.ASSISTANT and e.task == self._task]
        if fold.cards_awaiting_approval(events, self._task or ""):
            reason = kinds.INPUT_REQUIRED
        elif replies and replies[-1].payload["finish_reason"] in FAILED_REPLIES:
            reason = kinds.FAILED
        else:
            reason = kinds.COMPLETED
        await self._close(events, turn, reason)

    async def _note_sources(self, events: list[Event]) -> None:
        """When the turn read sources: the links and amounts of its answer that no source (and not the
        person) gave are named, and the sources the answer draws on are shown with their link and date."""
        mine = [e for e in events if e.task == self._task]
        reads = [
            e for e in mine if e.type == kinds.TOOL and e.payload.get("server") in sources.SOURCE_SERVERS
        ]
        if not reads:
            return
        answer = next((e.payload.get("text", "") for e in reversed(mine) if e.type == kinds.ASSISTANT), "")
        said = " ".join(e.payload.get("text", "") for e in events if e.type == kinds.USER)
        read = " ".join(e.payload["result_text"] for e in reads)
        if missing := sources.ungrounded(answer, read, said):
            logs.event(logger, "ungrounded", figures=len(missing))
            await self._notice(sources.NOT_IN_SOURCES.format(items=", ".join(missing)))
        references = [r for e in reads for r in e.payload.get("sources", [])]
        for reference in sources.drawn_on(references, answer):
            await self._notice(sources.source_line(reference))

    async def _notice(self, text: str) -> None:
        await self._log.append(kinds.NOTICE, {"level": "info", "text": text}, task=self._task)

    async def _close(self, events: list[Event], turn: Event, reason: str, **marks: Any) -> None:
        replies = [
            e.payload["finish_reason"] for e in events if e.type == kinds.ASSISTANT and e.task == self._task
        ]
        payload = {"task": self._task, "reason": reason, "finish_reasons": replies, "rounds": len(replies)}
        await self._log.append(kinds.TURN_FINISHED, {**payload, **marks}, task=self._task)
        self._record(events, turn, reason, str(marks.get("cause", "")))

    def _record(self, events: list[Event], turn: Event, reason: str, cause: str) -> None:
        """The turn's data point: how it ended, how long it took, and the tokens its rounds used."""
        replies = [e for e in events if e.type == kinds.ASSISTANT and e.task == self._task]
        usage = [r.payload.get("usage") or {} for r in replies]
        prompt = sum(int(u.get("prompt_tokens", 0)) for u in usage)
        completion = sum(int(u.get("completion_tokens", 0)) for u in usage)
        self._metrics.turn(reason, cause, len(replies), self._clock() - turn.at, prompt, completion)

    async def stop(self) -> bool:
        """Ends what the person asked to stop, after the task that was running it has been cancelled.

        What the model had said stays as the reply. Calls that had no result get one that says they were
        stopped. The turn finishes as `cancelled`, marked with the log's end at that moment: everything
        the person had sent by then is settled, and only what arrives after it is answered."""
        events = await self._log.context()
        turn, action = fold.open_turn(events), fold.next_action(events)
        if turn is None and isinstance(action, fold.Idle):
            return False
        upto = await self._log.last_seq()
        if turn is None:
            driver = action.driver if isinstance(action, fold.ModelRound) else action.assistant
            turn = await self._start(driver)
        self._task = turn.payload["task"]
        await self._settle_round(turn)
        await self._stop_calls(STOPPED_TOOL)
        await self._close(await self._log.context(), turn, kinds.CANCELLED, upto=upto)
        return True

    async def _settle_round(self, turn: Event) -> None:
        stopped, self._round = self._round, None
        if stopped is None:
            await self._abort_open_messages(turn)
            return
        answered = {e.payload["message"] for e in await self._log.context() if e.type == kinds.ASSISTANT}
        if stopped.message not in answered:
            await self._reply(stopped.message, stopped.streamed.text, [], STOPPED_REPLY, stopped.upto)

    async def _stop_calls(self, why: str) -> None:
        """Gives every call that has no result one that says it was stopped, and why."""
        while isinstance(action := fold.next_action(await self._log.context()), fold.ToolRound):
            for call in action.calls:
                server, _, tool = call["name"].partition("__")
                payload = {
                    "call_id": call["id"],
                    "server": server,
                    "tool": tool,
                    "arguments": call_rules.arguments_of(call) or {},
                    "result_text": why,
                    "is_error": True,
                    "cancelled": True,
                }
                await self._log.append(kinds.TOOL, payload, task=self._task)
