# SPDX-License-Identifier: AGPL-3.0-or-later
"""Building a ChatCore from a Worker's bindings: the one place that knows which settings, database, model
client and connectors a chat's brain is made of."""

import time
from typing import Any

import httpx

from .binding import connector_client
from .chat_core import Alarms, ChatCore, Starter
from .db import D1
from .fanout import SocketPool
from .hub import build_hub
from .model import OpenAICompatible
from .reach.server import local_servers
from .settings import Settings

_client: httpx.AsyncClient | None = None


def env_reader(env: Any):
    def read(name: str) -> str | None:
        value = getattr(env, name, None)
        return None if value is None else str(value)

    return read


def http_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=30)
    return _client


def build_core(
    env: Any, chat_id: str, pool: SocketPool, alarms: Alarms, starter: Starter | None = None
) -> ChatCore:
    settings = Settings.from_env(env_reader(env))
    client = http_client()
    db = D1(env.DB)
    return ChatCore(
        chat_id,
        db,
        settings,
        OpenAICompatible(settings, client),
        build_hub(
            settings.mcp_url,
            settings.connectors,
            connector_client(env, settings.mcp_binding, client),
            settings.mcp_token,
            local_servers(settings, db, client),
        ),
        pool,
        alarms,
        lambda: int(time.time() * 1000),
        starter,
    )
