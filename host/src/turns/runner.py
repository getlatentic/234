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
from . import fold, kinds, messages, quote_events
from .budget import take_model_call
from .card_calls import card_ref
from .compaction.compactor import Compactor
from .db import Db
from .eventlog import Event, EventLog
from .hub import Hub, HubError, ToolOutcome, refused
from .idempotency import derive_key
from .ledger_owner import is_account, ledger_owner
from .memory import NOT_AN_ACCOUNT, is_memory_tool, notes_message, offered, read_index, with_notes
from .model import ContextTooLong, Finished, Model, ModelError, TextDelta
from .prompt import system_prompt
from .settings import Settings
from .tokens import request_tokens

logger = logging.getLogger(__name__)

BUDGET_NOTICES = {
    "global": "Today's model budget is used up. Try again tomorrow.",
    "visitor": "You have used today's share of the model budget. Try again tomorrow.",
}
TOO_SLOW = "The model took too long to answer."
LENGTH_NOTICE = "The model ran out of room before it finished its reply."
ROUNDS_NOTICE = "The assistant stopped after too many tool calls in one turn."
UNREACHABLE = "The connector could not be reached."
BAD_ARGUMENTS = "The tool arguments were not valid JSON."
INTERRUPTED = "The assistant was interrupted and could not continue."
STOPPED_TOOL = "Stopped by the person before it finished."
FAILED_REPLIES = ("error", "budget")
STOPPED_REPLY = "cancelled"


def new_id() -> str:
    return secrets.token_hex(8)


@dataclass
class _Streamed:
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
    ) -> None:
        self._log, self._db, self._model, self._hub = log, db, model, hub
        self._settings, self._owner, self._clock, self._ids = settings, owner, clock, ids
        self._task: str | None = None
        self._round: _Round | None = None
        self._compactor = Compactor(log, model, settings, clock, self._permit_model_call)

    async def run(self, resumed: bool = False) -> None:
        """Runs until the log has nothing left for the runner to do."""
        if resumed and not await self._resume():
            return
        while True:
            events = await self._log.context()
            turn = fold.open_turn(events)
            self._task = turn.payload["task"] if turn else None
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
                    for call in calls:
                        await self._run_tool(call, assistant.payload["tool_calls"])

    async def _start(self, driver: Event) -> Event:
        self._task = driver.task or self._ids()
        return await self._log.append(
            kinds.TURN_STARTED, {"task": self._task, "trigger": driver.seq}, task=self._task
        )

    def _rounds_used(self, events: list[Event]) -> int:
        return sum(1 for e in events if e.type == kinds.ASSISTANT and e.task == self._task)

    async def _resume(self) -> bool:
        """False when the turn has failed too often to try again; otherwise it is marked resumed."""
        events = await self._log.context()
        turn = fold.open_turn(events)
        if turn is None:
            return not isinstance(fold.next_action(events), fold.Idle)
        self._task = turn.payload["task"]
        resumes = sum(1 for e in events if e.type == kinds.TURN_RESUMED and e.task == self._task)
        if resumes >= self._settings.max_resumes:
            await self._log.append(kinds.NOTICE, {"level": "error", "text": INTERRUPTED}, task=self._task)
            await self._close(events, turn, kinds.FAILED)
            return False
        await self._abort_open_messages(turn)
        await self._log.append(kinds.TURN_RESUMED, {"task": self._task}, task=self._task)
        return True

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
        if verdict := await take_model_call(
            self._db,
            self._owner,
            self._clock(),
            self._settings.visitor_model_calls_per_day,
            self._settings.model_calls_per_day,
        ):
            await self._log.append(
                kinds.NOTICE, {"level": "info", "text": BUDGET_NOTICES[verdict]}, task=self._task
            )
            await self._reply(message, "", [], "budget", upto)
            return
        streamed = _Streamed()
        try:
            system = system_prompt(self._settings.connectors, memory=is_account(self._owner))
            tools = offered(await self._hub.model_tools(), self._owner)
            index = await read_index(self._hub, self._owner)
            head = with_notes(system, index)
            notes = notes_message(index) if index else None
            events = await self._compacted(events, head, tools)
            upto = events[-1].seq
            try:
                sent = await self._stream_round(events, upto, message, streamed, system, tools, notes)
            except ContextTooLong:
                events = await self._squeezed(events, head, tools)
                upto = events[-1].seq
                sent = await self._stream_round(events, upto, message, streamed, system, tools, notes)
        except (ModelError, HubError, httpx.HTTPError) as error:
            text = str(error) if isinstance(error, ModelError | HubError) else UNREACHABLE
            await self._log.append(kinds.NOTICE, {"level": "error", "text": text}, task=self._task)
            await self._reply(message, streamed.text, [], "error", upto)
            return
        finished = streamed.finished
        assert finished is not None
        if finished.reason == "length" and not finished.tool_calls:
            await self._log.append(kinds.NOTICE, {"level": "info", "text": LENGTH_NOTICE}, task=self._task)
        calls = call_rules.with_distinct_ids(finished.tool_calls, call_rules.used_ids(events), message)
        measured = (
            {"estimate": request_tokens(sent, tools), "usage": finished.usage} if finished.usage else {}
        )
        await self._reply(message, streamed.text, calls, finished.reason, upto, measured)

    async def _stream_round(
        self,
        events: list[Event],
        upto: int,
        message: str,
        streamed: _Streamed,
        system: str,
        tools: list[dict[str, Any]],
        notes: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Asks the model once, for the conversation as it stands; the messages sent."""
        self._round = _Round(message, upto, streamed)
        sent = messages.render(events, system, notes)
        await self._stream(streamed, message, sent, tools)
        return sent

    async def _squeezed(self, events: list[Event], system: str, tools: list[dict[str, Any]]) -> list[Event]:
        """The events after the endpoint has refused the context as too long: trimmed, or as they were."""
        logger.warning("Chat %s was refused as too long for the model; trimming it", self._log.chat_id)
        return await self._log.context() if await self._compactor.squeeze(system, tools) else events

    async def _compacted(self, events: list[Event], system: str, tools: list[dict[str, Any]]) -> list[Event]:
        """The events the round reads, after a compaction if the context needed one. A compaction that goes
        wrong never fails the round: it is read without it."""
        try:
            if await self._compactor.before_round(events, system, tools):
                return await self._log.context()
        except Exception:
            logger.exception("Compaction of chat %s failed; the round goes on without it", self._log.chat_id)
        return events

    async def _permit_model_call(self) -> bool:
        """A summary is a model call and counts against the same daily caps as a reply."""
        verdict = await take_model_call(
            self._db,
            self._owner,
            self._clock(),
            self._settings.visitor_model_calls_per_day,
            self._settings.model_calls_per_day,
        )
        return verdict is None

    def use_owner(self, owner: str) -> None:
        """The chat's owner as it is now: signing in moves a visitor's chats to their account while this
        runner may be alive, and the next turn is theirs."""
        self._owner = owner

    def close_compaction(self) -> None:
        self._compactor.close()

    async def compact(self, keep_recent_tokens: int | None = None) -> Event | None:
        """Compacts now, at the person's request: the event written, or None when nothing could be covered."""
        try:
            tools = await self._hub.model_tools()
        except HubError, httpx.HTTPError:
            tools = []
        return await self._compactor.manual(
            system_prompt(self._settings.connectors), tools, keep_recent_tokens
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

    async def _run_tool(self, call: dict[str, Any], reply_calls: list[dict[str, Any]]) -> None:
        arguments = call_rules.arguments_of(call)
        if arguments is None:
            outcome = refused("", call["name"], BAD_ARGUMENTS)
        elif twin := await self._twin_in_reply(call, reply_calls):
            outcome = await self._repeat_of(call["name"], twin)
        else:
            outcome = await self._call(call, arguments)
        await self._log.append(
            kinds.TOOL,
            {
                "call_id": call["id"],
                "server": outcome.server,
                "tool": outcome.tool,
                "arguments": arguments or {},
                "result_text": outcome.text,
                "is_error": outcome.is_error,
            },
            task=self._task,
        )
        ref = card_ref(outcome.result)
        if outcome.card_uri and not outcome.is_error and ref:
            payload = {
                "server": outcome.server,
                "tool": outcome.tool,
                "resource_uri": outcome.card_uri,
                "result": outcome.result,
            }
            await self._log.append(kinds.CARD, payload, task=self._task, ref=ref)
            await quote_events.follow(self._hub, self._settings, outcome, ledger_owner(self._owner))

    async def _twin_in_reply(
        self, call: dict[str, Any], reply_calls: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        """The earlier call of this reply that made the same quote request, when this one repeats it."""
        twin = call_rules.earlier_twin(reply_calls, call)
        return twin if twin and await self._hub.keyed(call["name"]) else None

    async def _repeat_of(self, name: str, twin: dict[str, Any]) -> ToolOutcome:
        events = await self._log.context()
        first = next(e for e in events if e.type == kinds.TOOL and e.payload["call_id"] == twin["id"])
        server, _, tool = name.partition("__")
        text = call_rules.REPEATED + first.payload["result_text"]
        result = {"isError": first.payload["is_error"], "content": [{"type": "text", "text": text}]}
        return ToolOutcome(server, tool, result, None)

    async def _call(self, call: dict[str, Any], arguments: dict[str, Any]) -> ToolOutcome:
        if is_memory_tool(call["name"]) and not is_account(self._owner):
            server, _, tool = call["name"].partition("__")
            return refused(server, tool, NOT_AN_ACCOUNT)
        owner = ledger_owner(self._owner)
        key = derive_key(owner, self._log.chat_id, call["id"])
        try:
            return await self._hub.call_model_tool(call["name"], arguments, owner, key)
        except HubError, httpx.HTTPError:
            server, _, tool = call["name"].partition("__")
            return refused(server, tool, UNREACHABLE)

    async def _stop_at_limit(self, events: list[Event], turn: Event) -> None:
        await self._log.append(kinds.NOTICE, {"level": "info", "text": ROUNDS_NOTICE}, task=self._task)
        await self._close(events, turn, kinds.MAX_ROUNDS)

    async def _finish(self, events: list[Event], turn: Event) -> None:
        replies = [e for e in events if e.type == kinds.ASSISTANT and e.task == self._task]
        if fold.cards_awaiting_approval(events, self._task or ""):
            reason = kinds.INPUT_REQUIRED
        elif replies and replies[-1].payload["finish_reason"] in FAILED_REPLIES:
            reason = kinds.FAILED
        else:
            reason = kinds.COMPLETED
        await self._close(events, turn, reason)

    async def _close(self, events: list[Event], turn: Event, reason: str, **marks: Any) -> None:
        replies = [
            e.payload["finish_reason"] for e in events if e.type == kinds.ASSISTANT and e.task == self._task
        ]
        payload = {"task": self._task, "reason": reason, "finish_reasons": replies, "rounds": len(replies)}
        await self._log.append(kinds.TURN_FINISHED, {**payload, **marks}, task=self._task)

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
        await self._stop_calls()
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

    async def _stop_calls(self) -> None:
        while isinstance(action := fold.next_action(await self._log.context()), fold.ToolRound):
            for call in action.calls:
                server, _, tool = call["name"].partition("__")
                payload = {
                    "call_id": call["id"],
                    "server": server,
                    "tool": tool,
                    "arguments": call_rules.arguments_of(call) or {},
                    "result_text": STOPPED_TOOL,
                    "is_error": True,
                    "cancelled": True,
                }
                await self._log.append(kinds.TOOL, payload, task=self._task)
