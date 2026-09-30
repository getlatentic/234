# SPDX-License-Identifier: AGPL-3.0-or-later
"""The turn runners that are not a Durable Object, kept as the measured alternatives (docs/durable-chat.md).

Both run the same TurnRunner over the same log; they differ in what keeps the turn alive after the request
that started it has answered:

* `waituntil`: `ctx.waitUntil` on the Worker that took the message.
* `queue`: a message on a Queue, consumed by the Worker's queue handler.

Neither can push to a socket, so their clients follow the log by polling (the server-sent events view).
"""

import asyncio
from typing import Any

from js import Object
from pyodide.ffi import to_js

from ..assembly import build_core
from ..chat_core import ChatCore, Starter
from .drive import drive

current_context: Any = None


class NoSockets:
    def sockets(self) -> list[Any]:
        return []

    def key(self, socket: Any) -> str:
        return ""

    def sent(self, socket: Any) -> int | None:
        return None

    def mark(self, socket: Any, seq: int | None) -> None:
        return None

    def send(self, socket: Any, text: str) -> None:
        return None


class NoAlarms:
    async def arm(self, at_ms: int) -> None:
        return None

    async def disarm(self) -> None:
        return None


def local_core(env: Any, chat_id: str, starter: Starter | None = None) -> ChatCore:
    return build_core(env, chat_id, NoSockets(), NoAlarms(), starter)


async def start_with_wait_until(core: ChatCore, resumed: bool) -> None:
    current_context.waitUntil(asyncio.ensure_future(drive(core, resumed)))


def queue_starter(env: Any):
    async def start(core: ChatCore, resumed: bool) -> None:
        await env.TURNS.send(
            to_js({"chat": core.chat_id, "resumed": resumed}, dict_converter=Object.fromEntries)
        )

    return start


async def consume(batch: Any, env: Any) -> None:
    """The Queue's consumer: one message is one chat to run. A turn that fails is redelivered, and the
    runner resumes from the log."""
    for message in batch.messages:
        body = message.body.to_py() if hasattr(message.body, "to_py") else message.body
        redelivered = int(getattr(message, "attempts", 1) or 1) > 1
        await drive(local_core(env, body["chat"]), bool(body.get("resumed")) or redelivered)
        message.ack()
