# SPDX-License-Identifier: AGPL-3.0-or-later
"""Building a ChatCore from a Worker's bindings: the one place that knows which settings, database, model
client and connectors a chat's brain is made of."""

import time
from dataclasses import replace
from typing import Any

import httpx

from .binding import connector_client
from .chat_core import Alarms, ChatCore, Starter
from .db import D1
from .fanout import SocketPool
from .hub import build_hub
from .metrics import metrics_of
from .model import OpenAICompatible
from .reach.server import local_servers
from .research.core import ResearchCore
from .research.launcher import DoLauncher
from .research.server import SERVER as RESEARCH_SERVER
from .research.server import research_server
from .research.store import CONNECTORS as RESEARCH_CONNECTORS
from .research.store import ResearchStore
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
    env: Any,
    chat_id: str,
    pool: SocketPool,
    alarms: Alarms,
    starter: Starter | None = None,
    research: bool = False,
) -> ChatCore:
    """The brain of a chat; of a research run's chat when `research`, which reads sources and the web only and
    reports to the chat it researches for."""
    settings = Settings.from_env(env_reader(env))
    client = http_client()
    db = D1(env.DB)
    clock = lambda: int(time.time() * 1000)  # noqa: E731
    model = OpenAICompatible(settings, client)
    if research:
        return _research_core(env, chat_id, replace_limits(settings), db, model, pool, alarms, clock, client)
    local = {
        **local_servers(settings, db, client),
        RESEARCH_SERVER: research_server(settings, db, clock, DoLauncher(env)),
    }
    hub = build_hub(
        settings.mcp_url,
        settings.connectors,
        connector_client(env, settings.mcp_binding, client),
        settings.mcp_token,
        local,
    )
    return ChatCore(chat_id, db, settings, model, hub, pool, alarms, clock, starter, metrics_of(env))


def replace_limits(settings: Settings) -> Settings:
    """A research run reads more than a turn does: its own allowance of source calls and rounds."""
    return replace(
        settings, searches_per_turn=settings.research_searches, max_tool_rounds=settings.research_rounds
    )


def _research_core(
    env: Any, chat_id: str, settings: Settings, db: D1, model: OpenAICompatible, pool: SocketPool,
    alarms: Alarms, clock: Any, client: httpx.AsyncClient,
) -> ChatCore:  # fmt: skip
    hub = build_hub(
        settings.mcp_url,
        tuple(c for c in settings.connectors if c in RESEARCH_CONNECTORS.split(",")),
        connector_client(env, settings.mcp_binding, client),
        settings.mcp_token,
    )
    return ResearchCore(
        chat_id, db, settings, model, hub, pool, alarms, clock, None, metrics_of(env),
        store=ResearchStore(db, clock), reporter=DoLauncher(env).report,
    )  # fmt: skip
