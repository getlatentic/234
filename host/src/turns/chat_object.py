# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Durable Object: one per chat, and the only writer of that chat's log.

It adapts the runtime to ChatCore: RPC methods for the Django host (JSON in, JSON out, which needs no
conversion between Python and JavaScript), hibernating WebSockets for live clients, and the alarm as the
watchdog that restarts a turn a restart cut off. Django is never imported here.
"""

import asyncio
import json
import logging
import secrets
from typing import Any

import httpx
from js import Object, WebSocketPair, WebSocketRequestResponsePair
from pyodide.ffi import to_js
from workers import DurableObject, Response

from . import kinds
from .assembly import build_core
from .chat_core import ChatCore
from .hub import HubError

log = logging.getLogger(__name__)

PING = "ping"
PONG = "pong"


def _js(value: dict[str, Any]) -> Any:
    return to_js(value, dict_converter=Object.fromEntries)


class HibernatingSockets:
    """The pool of sockets the runtime keeps for this object across hibernation. A socket's cursor is
    its serialized attachment."""

    def __init__(self, ctx: Any) -> None:
        self._ctx = ctx

    def sockets(self) -> list[Any]:
        return list(self._ctx.getWebSockets())

    @staticmethod
    def _attachment(socket: Any) -> dict[str, Any]:
        found = socket.deserializeAttachment()
        return found.to_py() if hasattr(found, "to_py") else {}

    def key(self, socket: Any) -> str:
        return str(self._attachment(socket).get("id", ""))

    def sent(self, socket: Any) -> int | None:
        value = self._attachment(socket).get("sent")
        return None if value is None else int(value)

    def mark(self, socket: Any, seq: int | None) -> None:
        socket.serializeAttachment(_js({**self._attachment(socket), "sent": seq}))

    def send(self, socket: Any, text: str) -> None:
        try:
            socket.send(text)
        except Exception:
            log.debug("A socket refused a frame; its close event will clean up", exc_info=True)


class StorageAlarms:
    def __init__(self, storage: Any) -> None:
        self._storage = storage

    async def arm(self, at_ms: int) -> None:
        await self._storage.setAlarm(at_ms)

    async def disarm(self) -> None:
        await self._storage.deleteAlarm()


class Chat(DurableObject):
    def __init__(self, ctx: Any, env: Any) -> None:
        super().__init__(ctx, env)
        self._core: ChatCore | None = None
        self._recovery: asyncio.Future[None] | None = None
        self._pool = HibernatingSockets(ctx)

    async def _core_for(self, chat_id: str | None = None) -> ChatCore:
        if self._core is None:
            if chat_id is None:
                chat_id = await self.ctx.storage.get("chat_id")
            else:
                await self.ctx.storage.put("chat_id", chat_id)
            self._core = build_core(self.env, chat_id, self._pool, StorageAlarms(self.ctx.storage))
            self._recovery = asyncio.ensure_future(self._core.recover())
        return self._core

    async def fetch(self, request: Any) -> Any:
        chat_id = request.url.split("/c/", 1)[1].split("/", 1)[0]
        await self._core_for(chat_id)
        pair = WebSocketPair.new()
        client, server = pair.object_values()
        self.ctx.acceptWebSocket(server)
        self.ctx.setWebSocketAutoResponse(WebSocketRequestResponsePair.new(PING, PONG))
        server.serializeAttachment(_js({"id": secrets.token_hex(8), "sent": None}))
        return Response(None, status=101, web_socket=client)

    async def webSocketMessage(self, socket: Any, message: Any) -> None:
        try:
            attach = json.loads(str(message)).get("attach")
        except ValueError:
            return
        if isinstance(attach, int):
            await (await self._core_for()).attach(socket, attach)

    async def webSocketClose(self, socket: Any, code: Any, reason: Any, was_clean: Any) -> None:
        await (await self._core_for()).detach(socket)
        try:
            socket.close()
        except Exception:
            log.debug("The socket was already closed", exc_info=True)

    async def webSocketError(self, socket: Any, error: Any) -> None:
        await (await self._core_for()).detach(socket)

    async def alarm(self) -> None:
        await (await self._core_for()).on_alarm()

    async def submit(self, chat_id: str, kind: str, text: str, task: str) -> str:
        core = await self._core_for(chat_id)
        if kind == kinds.CARD_CONTEXT:
            return json.dumps(await core.note(text))
        return json.dumps(await core.submit(kind, text, task or None))

    async def cancel(self, chat_id: str) -> str:
        return json.dumps(await (await self._core_for(chat_id)).cancel())

    async def compact(self, chat_id: str, keep_recent_tokens: int) -> str:
        core = await self._core_for(chat_id)
        return json.dumps(await core.compact(keep_recent_tokens if keep_recent_tokens >= 0 else None))

    async def card_call(self, chat_id: str, server: str, name: str, arguments_json: str) -> str:
        core = await self._core_for(chat_id)
        try:
            return json.dumps({"result": await core.card_call(server, name, json.loads(arguments_json))})
        except (HubError, httpx.HTTPError) as refused:
            return json.dumps(
                {
                    "error": str(refused)
                    if isinstance(refused, HubError)
                    else "The connector could not be reached."
                }
            )

    async def refresh_card(self, chat_id: str, quote_id: str) -> str:
        return json.dumps(await (await self._core_for(chat_id)).refresh_card(quote_id))

    async def quote_ended(self, chat_id: str, quote_id: str, event_id: str, text: str) -> str:
        return json.dumps(await (await self._core_for(chat_id)).quote_ended(quote_id, event_id, text))

    async def purge(self, chat_id: str) -> str:
        await (await self._core_for(chat_id)).purge()
        await self.ctx.storage.deleteAll()
        for socket in self._pool.sockets():
            socket.close(1000, "deleted")
        self._core = None
        return "true"
