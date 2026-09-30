# SPDX-License-Identifier: AGPL-3.0-or-later
"""Running a chat's turns from outside a Durable Object: under a lease, until the log has nothing left,
and again if an input arrived while the lease was being let go."""

import asyncio
import contextlib

from .. import fold
from ..chat_core import ChatCore
from .lease import Lease, LeaseLost

HEARTBEAT_SECONDS = 10


async def _keep_lease(lease: Lease, work: asyncio.Future) -> None:
    """Renews the lease while the turn runs; if it is lost the turn is stopped, not left to run twice."""
    while True:
        await asyncio.sleep(HEARTBEAT_SECONDS)
        try:
            await lease.renew()
        except LeaseLost:
            work.cancel()
            return


async def drive(core: ChatCore, resumed: bool = False) -> None:
    lease = Lease(core.database, core.chat_id, core.clock)
    while await lease.claim():
        runner = await core.new_runner()
        work = asyncio.ensure_future(runner.run(resumed=resumed))
        beat = asyncio.ensure_future(_keep_lease(lease, work))
        try:
            await work
        except asyncio.CancelledError:
            return
        finally:
            beat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await beat
            await lease.release()
        resumed = False
        if isinstance(fold.next_action(await core.log.context()), fold.Idle):
            return
