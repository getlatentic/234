# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pushing the log to attached sockets, each at its own cursor.

A socket is sent event N+1 only after event N, so it never sees a gap or a repeat: an event that is not
next in line makes the socket catch up from the log instead. The cursor lives on the socket (as a
hibernation attachment), not in memory, so it survives the object being evicted and woken.
"""

import asyncio
import json
from typing import Any, Protocol

from .eventlog import Event, EventLog

CATCH_UP_BATCH = 200


class SocketPool(Protocol):
    def sockets(self) -> list[Any]: ...

    def key(self, socket: Any) -> str: ...

    def sent(self, socket: Any) -> int | None:
        """The last seq the socket has been sent, or None while it has not said where to start."""
        ...

    def mark(self, socket: Any, seq: int | None) -> None: ...

    def send(self, socket: Any, text: str) -> None: ...


def frame(event: Event) -> str:
    return json.dumps(event.wire(), ensure_ascii=False)


class Fanout:
    def __init__(self, pool: SocketPool, log: EventLog) -> None:
        self._pool = pool
        self._log = log
        self._locks: dict[str, asyncio.Lock] = {}

    def _deliver(self, socket: Any, event: Event) -> bool:
        """Sends the event when it is next in line for the socket; False when it is not."""
        sent = self._pool.sent(socket)
        if sent is None or event.seq != sent + 1:
            return False
        self._pool.send(socket, frame(event))
        self._pool.mark(socket, event.seq)
        return True

    async def publish(self, event: Event) -> None:
        for socket in self._pool.sockets():
            sent = self._pool.sent(socket)
            if sent is not None and event.seq > sent and not self._deliver(socket, event):
                await self.catch_up(socket)

    async def attach(self, socket: Any, since: int) -> None:
        """Starts a socket after `since` (0 for everything) and brings it up to date."""
        self._pool.mark(socket, since)
        await self.catch_up(socket)
        if since > await self._log.last_seq():
            self._pool.send(socket, json.dumps({"reset": True}))

    async def catch_up(self, socket: Any) -> None:
        async with self._locks.setdefault(self._pool.key(socket), asyncio.Lock()):
            while True:
                sent = self._pool.sent(socket)
                if sent is None:
                    return
                events = await self._log.read(after=sent, limit=CATCH_UP_BATCH)
                if not events:
                    return
                for event in events:
                    if self._pool.sent(socket) == event.seq - 1:
                        self._deliver(socket, event)

    def forget(self, socket: Any) -> None:
        self._locks.pop(self._pool.key(socket), None)
