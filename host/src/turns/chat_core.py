# SPDX-License-Identifier: AGPL-3.0-or-later
"""One chat's brain: everything a Durable Object does, apart from talking to the runtime.

It is the single writer of the chat's log. It records inputs, runs the turn loop in the background so a
turn outlives every client, pushes each new event to attached sockets, relays a card's tool calls, and
recovers a turn that was cut off. The Durable Object class (chat_object.py) only adapts the runtime to
the small interfaces used here.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from . import fold, kinds, permissions, scope
from .card_calls import CardCalls
from .db import Db
from .eventlog import Event, EventLog
from .fanout import Fanout, SocketPool
from .hub import Hub, HubError
from .inputs import InputRefused, clean_text
from .ledger_owner import is_account, ledger_owner
from .model import Model
from .runner import TurnRunner, new_id
from .settings import Settings

log = logging.getLogger(__name__)

Starter = Callable[["ChatCore", bool], Awaitable[None]]


class Alarms(Protocol):
    async def arm(self, at_ms: int) -> None: ...

    async def disarm(self) -> None: ...

    async def unchanged(self, last_seq: int) -> int:
        """Records the log's end at this alarm; how many alarms in a row, this one included, found it
        unchanged since the one before (0 when it moved)."""
        ...


class ChatCore:
    def __init__(
        self,
        chat_id: str,
        db: Db,
        settings: Settings,
        model: Model,
        hub: Hub,
        pool: SocketPool,
        alarms: Alarms,
        clock: Callable[[], int],
        starter: Starter | None = None,
    ) -> None:
        self.chat_id = chat_id
        self._db, self._settings, self._model, self._hub = db, settings, model, hub
        self._alarms, self._clock, self._starter = alarms, clock, starter
        self.log = EventLog(db, chat_id, clock, on_append=self._publish)
        self._fanout = Fanout(pool, self.log)
        self._cards = CardCalls(db, self.log, hub, self.note, self._ledger_owner, self._has_memory)
        self._pool = pool
        self._driver: asyncio.Task[None] | None = None
        self._runner: TurnRunner | None = None
        self._making_runner = asyncio.Lock()
        self._more_to_do = False
        self._resume_next = False
        self._erased = False

    async def _publish(self, event: Event) -> None:
        await self._fanout.publish(event)

    async def _owner_of_chat(self) -> str:
        """Read each time, never kept: signing in moves a visitor's chats to their account (accounts/adopt.py)
        while this object may be alive, and the next call must already be made for the new owner."""
        row = await self._db.row("SELECT owner FROM chat_chat WHERE id = ?", self.chat_id)
        if row is None:
            raise HubError("There is no such chat.")
        return row["owner"]

    async def _ledger_owner(self) -> str:
        return ledger_owner(await self._owner_of_chat())

    async def _has_memory(self) -> bool:
        return is_account(await self._owner_of_chat())

    async def submit(
        self, kind: str, text: str, task: str | None = None, scopes: list[str] | None = None
    ) -> dict[str, Any]:
        """Records what the person (or a card, or an A2A caller) said and makes sure a turn answers it.
        `scopes`: what a personal agent's message may do as the person's account (turns/permissions.py)."""
        try:
            text = clean_text(text)
        except InputRefused as refused:
            return {"error": refused.code, "message": str(refused)}
        events = await self.log.context()
        open_turn = fold.open_turn(events)
        continuing = (open_turn.payload["task"] if open_turn else None) or (
            fold.waiting_task(events) if kind == kinds.CARD_MESSAGE else None
        )
        task = task or continuing or new_id()
        payload = {"text": text} if scopes is None else {"text": text, permissions.SCOPES_FIELD: scopes}
        event = await self.log.append(kind, payload, task=task)
        await self.wake()
        return {"seq": event.seq, "task": task}

    async def note(self, text: str) -> dict[str, Any]:
        """What a card tells the model (ui/update-model-context): kept, and never a reason to reply. A note
        names its quote and what the card shows, so a card that says it again (another tab, a reload that
        draws the chat's old cards) adds nothing: a note already in the log is kept once."""
        try:
            text = clean_text(text)
        except InputRefused as refused:
            return {"error": refused.code, "message": str(refused)}
        known = await self._db.row(
            "SELECT seq FROM chat_event WHERE chat_id = ? AND type = ? "
            "AND json_extract(payload, '$.text') = ? LIMIT 1",
            self.chat_id, kinds.CARD_CONTEXT, text,
        )  # fmt: skip
        if known is not None:
            return {"seq": known["seq"]}
        event = await self.log.append(kinds.CARD_CONTEXT, {"text": text})
        return {"seq": event.seq}

    async def wake(self, resumed: bool = False) -> None:
        """Makes sure the turn loop is running. A loop that is running looks at the log once more before
        it stops, so an input that arrives while it works is never missed."""
        if self._erased:
            return None
        if self._starter is not None:
            return await self._starter(self, resumed)
        self._more_to_do = True
        self._resume_next = self._resume_next or resumed
        if not self.running:
            self._driver = asyncio.ensure_future(self._drive())

    async def new_runner(self) -> TurnRunner:
        owner = await self._owner_of_chat()
        row = await self._db.row("SELECT connectors FROM chat_chat WHERE id = ?", self.chat_id)
        servers = scope.servers_of(row["connectors"] if row else "")
        return TurnRunner(
            self.log, self._db, self._model, self._hub, self._settings, owner, self._clock, servers=servers
        )

    async def _the_runner(self) -> TurnRunner:
        """The one runner of this chat: its compactor serialises compactions, the turns' and the person's."""
        async with self._making_runner:
            if self._runner is None:
                self._runner = await self.new_runner()
            else:
                self._runner.use_owner(await self._owner_of_chat())
            return self._runner

    async def _drive(self) -> None:
        try:
            runner = await self._the_runner()
            while self._more_to_do:
                self._more_to_do = False
                resumed, self._resume_next = self._resume_next, False
                await self._alarms.arm(self._clock() + self._settings.watchdog_seconds * 1000)
                await runner.run(resumed=resumed)
                if not self._more_to_do:
                    await self._alarms.disarm()
        except Exception:
            log.exception("The turn loop for chat %s stopped", self.chat_id)

    async def cancel(self) -> dict[str, Any]:
        """Stops the turn that is answering the person, keeping what was said so far. A message that
        arrives after the stop is answered as usual."""
        if self._erased:
            return {"cancelled": False}
        self._more_to_do = False
        if self._driver is not None and not self._driver.done():
            self._driver.cancel()
            await asyncio.gather(self._driver, return_exceptions=True)
        stopped = await (await self._the_runner()).stop()
        await self._alarms.disarm()
        if not isinstance(fold.next_action(await self.log.context()), fold.Idle):
            await self.wake()
        return {"cancelled": stopped}

    async def compact(self, keep_recent_tokens: int | None = None) -> dict[str, Any]:
        """Summarises the older part of the conversation now, whatever its size. Requests that arrive together
        make one compaction; a chat being deleted makes none."""
        if self._erased:
            return {"compacted": False}
        event = await (await self._the_runner()).compact(keep_recent_tokens)
        if event is None:
            return {"compacted": False}
        payload = event.payload
        return {
            "compacted": True,
            "seq": event.seq,
            "trigger": payload["trigger"],
            "verified": payload["verified"],
            "tokens": payload["tokens"],
            "ms": payload["ms"],
        }

    @property
    def database(self) -> Db:
        return self._db

    @property
    def clock(self) -> Callable[[], int]:
        return self._clock

    @property
    def running(self) -> bool:
        return self._driver is not None and not self._driver.done()

    async def on_alarm(self) -> None:
        """The watchdog. While the loop lives it only rearms; a loop that is gone is started again. An alarm
        that keeps finding the log where the last one left it, with no loop running (a recovery that fails
        or raises each time), stops after a few, so it does not fire forever."""
        if self.running:
            await self._alarms.arm(self._clock() + self._settings.watchdog_seconds * 1000)
            return
        if await self._alarms.unchanged(await self.log.last_seq()) >= self._settings.max_alarm_strikes:
            log.error("The watchdog of chat %s found nothing changed %s times; it stops", self.chat_id,
                      self._settings.max_alarm_strikes)  # fmt: skip
            await self._alarms.disarm()
            return
        await self.recover()

    async def recover(self) -> None:
        """Continues a turn the previous instance of this object left half-done (it was restarted mid-turn):
        the log has an open turn, or an input nobody has answered, and no loop is running."""
        if self.running:
            return
        events = await self.log.context()
        if fold.open_turn(events) or not isinstance(fold.next_action(events), fold.Idle):
            await self.wake(resumed=True)

    async def card_call(self, server: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return await self._cards.call(server, name, arguments)

    async def refresh_card(self, quote_id: str) -> bool:
        return await self._cards.refresh(quote_id)

    async def quote_ended(self, quote_id: str, event_id: str, text: str) -> bool:
        """A quote.finished event: the card shows the ending, and the model is told and answers. An event
        delivered again (the same id) adds nothing."""
        await self._cards.refresh(quote_id)
        known = await self._db.row(
            "SELECT seq FROM chat_event WHERE chat_id = ? AND type = ? AND ref = ? LIMIT 1",
            self.chat_id, kinds.EVENT, event_id,
        )  # fmt: skip
        if known is not None:
            return False
        events = await self.log.context()
        task = fold.waiting_task(events) or new_id()
        await self.log.append(kinds.EVENT, {"text": text}, task=task, ref=event_id)
        await self.wake()
        return True

    async def attach(self, socket: Any, since: int) -> None:
        await self._fanout.attach(socket, since)

    async def detach(self, socket: Any) -> None:
        self._fanout.forget(socket)

    async def purge(self) -> None:
        self._erased = True
        if self._runner is not None:
            self._runner.close_compaction()
        if self._driver is not None and not self._driver.done():
            self._driver.cancel()
        await self._alarms.disarm()
        await self.log.erase()
