# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the connectors do after answering a request: MCP events (subscriptions, and delivery from the outbox)
and rechecks of quotes a provider wrote about. Each kind of work goes through a Queue where one is bound
(PROVIDER_JOBS, EVENT_JOBS) and runs at once where none is."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from .audit import Audit
from .clock import Clock
from .config import Settings
from .db import Db
from .events import Events
from .events.delivery import Delivery
from .events.subscriptions import Subscriptions
from .flows.context import Context
from .jobs import HeldJobs, InlineJobs, Job, QueueJobs
from .provider_hooks.rechecks import Rechecks
from .transport import Reply, Transport
from .wallet.topups import TopUps
from .wallet.withdrawal_outcome import WithdrawalOutcomes


class HostRouted:
    """Callbacks on the chat host's own origin go through its service binding (a Worker cannot fetch another
    Worker of its account by its public address); every other callback goes out as it is."""

    def __init__(self, host_origin: str | None, binding: Transport | None, other: Transport) -> None:
        self._host, self._binding, self._other = host_origin, binding, other

    async def send(self, method: str, url: str, *, headers, body, timeout_seconds) -> Reply:
        parts = urlsplit(url)
        own = self._binding is not None and f"{parts.scheme}://{parts.netloc}" == self._host
        chosen = self._binding if own else self._other
        return await chosen.send(method, url, headers=headers, body=body, timeout_seconds=timeout_seconds)


@dataclass(frozen=True)
class Background:
    events: Events
    delivery: Delivery
    rechecks: Rechecks
    topups: TopUps

    async def run(self, job: Job) -> None:
        """One job of either queue. A recheck can end a quote, whose events are then handed on."""
        if job["kind"] == "recheck":
            await self.rechecks.run(job["quote"])
            await self.delivery.drain()
        elif job["kind"] == "withdrawal":
            await self.rechecks.run_withdrawal(job["withdrawal"])
        elif job["kind"] == "deliver":
            await self.delivery.deliver(job["event"], job["subscription"])

    async def minute(self) -> None:
        """The Cron Trigger's: pending quotes and undecided withdrawals asked again, overdue quotes,
        withdrawals and top-ups expired, due events handed on."""
        await self.rechecks.sweep()
        await self.topups.expire_due()
        await self.delivery.drain()
        await self.delivery.prune()


def build_background(
    settings: Settings,
    db: Db,
    clock: Clock,
    audit: Audit,
    contexts: Mapping[str, Context],
    topups: TopUps,
    withdrawals: WithdrawalOutcomes,
    transport: Transport,
    queues: Mapping[str, Any] | None = None,
    jobs: HeldJobs | None = None,
) -> Background:
    """`jobs`, for tests, takes every job of both kinds and keeps it until it is run."""
    events = Events(Subscriptions(db), transport, clock, allow_loopback=settings.enable_test_routes)
    background = Background(
        events,
        Delivery(db, transport, clock, audit),
        Rechecks(db, dict(contexts), clock, audit, withdrawals),
        topups,
    )
    if jobs is not None:
        jobs.run = background.run
        background.delivery.jobs = background.rechecks.jobs = jobs
        return background
    queues = queues or {}
    inline = InlineJobs(background.run)
    background.delivery.jobs = QueueJobs(queues["EVENT_JOBS"]) if queues.get("EVENT_JOBS") else inline
    background.rechecks.jobs = QueueJobs(queues["PROVIDER_JOBS"]) if queues.get("PROVIDER_JOBS") else inline
    return background
