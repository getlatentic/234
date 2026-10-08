# SPDX-License-Identifier: AGPL-3.0-or-later
"""Every five minutes (the host's cron trigger) 234 checks what a turn needs besides the model: its
database, the chats' Durable Objects, and each connector over MCP (a `ping` after the handshake). Each check
is one health data point (metrics.py). No model is called, so a check spends nothing and takes nothing from
the day's model budget; whether the model answers shows in the turns' own data points."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from .metrics import Metrics, metrics_of

log = logging.getLogger(__name__)

DEADLINE_SECONDS = 10
HEALTH_OBJECT = "health-check"
"""The name of the Durable Object the check reaches: not a chat, it only answers `ping`."""

Probe = Callable[[], Awaitable[Any]]


async def run_checks(
    probes: dict[str, Probe], metrics: Metrics, clock: Callable[[], float]
) -> dict[str, bool]:
    """Runs each probe within the deadline and records it; what passed, by part."""
    passed = {}
    for part, probe in probes.items():
        began = clock()
        try:
            await asyncio.wait_for(probe(), DEADLINE_SECONDS)
            passed[part] = True
        except Exception:
            log.warning("Health check of %s failed", part, exc_info=True)
            passed[part] = False
        metrics.health(part, passed[part], int((clock() - began) * 1000))
    return passed


def probes_of(env: Any) -> dict[str, Probe]:
    from .assembly import env_reader, http_client
    from .binding import connector_client
    from .db import D1
    from .hub import build_hub
    from .settings import Settings

    settings = Settings.from_env(env_reader(env))
    client = http_client()
    hub = build_hub(
        settings.mcp_url,
        settings.connectors,
        connector_client(env, settings.mcp_binding, client),
        settings.mcp_token,
    )
    db = D1(env.DB)
    probes: dict[str, Probe] = {
        "database": lambda: db.row("SELECT 1 AS one"),
        "chats": lambda: env.CHAT.getByName(HEALTH_OBJECT).ping(),
    }
    for name in settings.connectors:
        probes[name] = lambda name=name: hub.ping(name)
    return probes


async def check(env: Any) -> dict[str, bool]:
    return await run_checks(probes_of(env), metrics_of(env), time.monotonic)
