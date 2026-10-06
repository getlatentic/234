# SPDX-License-Identifier: AGPL-3.0-or-later
"""Cloudflare Worker entrypoint: the four MCP connectors, the simulated checkout page, D1 ledger."""

import asyncio
from urllib.parse import urlsplit

from workers import Response, WorkerEntrypoint

from checkout.app import App, build_app
from checkout.background import HostRouted
from checkout.config import Settings
from checkout.db import D1
from checkout.errors import ConfigError
from checkout.http import handle
from checkout.transport import BindingFetch, WorkerFetch

_app: App | None = None
QUEUES = ("PROVIDER_JOBS", "EVENT_JOBS")


def _read_setting(env):
    def read(name: str) -> str | None:
        value = getattr(env, name, None)
        return None if value is None else str(value)

    return read


def _host_binding(env, settings: Settings):
    """The chat host's service binding, through which its own event callbacks are delivered."""
    if settings.host_binding is None:
        return None
    binding = getattr(env, settings.host_binding, None)
    if binding is None:
        raise ConfigError(f"The service binding {settings.host_binding} is configured but not bound.")
    return BindingFetch(binding)


def _app_for(env) -> App:
    global _app
    if _app is None:
        settings = Settings.from_env(_read_setting(env))
        callbacks = HostRouted(
            settings.host_public_url, _host_binding(env, settings), WorkerFetch(follow_redirects=False)
        )
        queues = {name: getattr(env, name, None) for name in QUEUES}
        _app = build_app(settings, D1(env.DB), callback_transport=callbacks, queues=queues)
    return _app


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        try:
            app = _app_for(self.env)
        except ConfigError as error:
            return Response(f"Refusing to start: {error.message}", status=500)
        location = urlsplit(request.url)
        headers = {key.lower(): value for key, value in request.headers.items()}
        raw = await request.bytes() if request.method not in ("GET", "HEAD") else b""
        result = await handle(app, str(request.method), location.path, headers, raw, location.query)
        if request.method == "POST":
            # A request that ended a quote has put its events in the outbox: hand them on after answering.
            self.ctx.waitUntil(asyncio.ensure_future(app.background.delivery.drain()))
        return Response(result.body, status=result.status, headers=result.headers)

    async def queue(self, batch, env, ctx):
        """PROVIDER_JOBS and EVENT_JOBS: a job that raises is retried by the Queue, then dead-lettered."""
        del ctx
        app = _app_for(env)
        for message in batch.messages:
            body = message.body.to_py() if hasattr(message.body, "to_py") else message.body
            try:
                await app.background.run(body)
            except Exception:
                message.retry()
                continue
            message.ack()

    async def scheduled(self, controller, env, ctx):
        """Every minute: pending quotes checked again, overdue ones expired, due events handed on."""
        del controller, ctx
        await _app_for(env).background.minute()
