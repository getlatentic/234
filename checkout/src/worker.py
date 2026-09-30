# SPDX-License-Identifier: AGPL-3.0-or-later
"""Cloudflare Worker entrypoint: the four MCP connectors, the simulated checkout page, D1 ledger."""

from urllib.parse import urlsplit

from workers import Response, WorkerEntrypoint

from checkout.app import App, build_app
from checkout.config import Settings
from checkout.db import D1
from checkout.errors import ConfigError
from checkout.http import handle
from checkout.transport import BindingFetch

_app: App | None = None


def _read_setting(env):
    def read(name: str) -> str | None:
        value = getattr(env, name, None)
        return None if value is None else str(value)

    return read


def _webhook_transport(env, settings: Settings):
    """The chat host is reached through its service binding when one is configured."""
    hook = settings.payment_webhook
    if hook is None or hook.binding is None:
        return None
    binding = getattr(env, hook.binding, None)
    if binding is None:
        raise ConfigError(f"The service binding {hook.binding} is configured but not bound.")
    return BindingFetch(binding)


def _app_for(env) -> App:
    global _app
    if _app is None:
        settings = Settings.from_env(_read_setting(env))
        _app = build_app(settings, D1(env.DB), webhook_transport=_webhook_transport(env, settings))
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
        return Response(result.body, status=result.status, headers=result.headers)
