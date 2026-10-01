# SPDX-License-Identifier: AGPL-3.0-or-later
"""Cloudflare Worker entrypoint. A WebSocket upgrade for a chat goes to that chat's Durable Object; every
other request goes to Django. The Durable Object class is exported from here, where the runtime looks."""

import os

os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "1")

from django_cf import handle_wsgi
from workers import Response, WorkerEntrypoint

from chat.socket_gate import chat_for_socket
from config.warm import warm_up
from config.wsgi import application
from turns.alternatives import runners
from turns.chat_object import Chat  # noqa: F401

warm_up()


class Default(WorkerEntrypoint):
    """`queue` and `runners.current_context` serve only the measured alternatives to the Durable Object
    (TURN_RUNNER=queue or waituntil); with the default runner neither is used."""

    async def queue(self, batch, *_):
        await runners.consume(batch, self.env)

    async def fetch(self, request):
        runners.current_context = self.ctx
        if (request.headers.get("upgrade") or "").lower() == "websocket":
            chat_id = chat_for_socket(request.url, request.headers.get("origin"))
            if chat_id is None:
                return Response("Forbidden", status=403)
            return await self.env.CHAT.getByName(chat_id).fetch(request)
        return await handle_wsgi(request, application, self.env)
