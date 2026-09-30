# SPDX-License-Identifier: AGPL-3.0-or-later
"""Waiting between polls of the log without holding up the Worker: inside a Worker the wait is async
(other requests run meanwhile), elsewhere it is an ordinary sleep."""

import time

from config import runtime

BUSY_POLL_SECONDS = 0.25
IDLE_POLL_SECONDS = 1.0
BUSY_WINDOW_SECONDS = 20


def poll_interval(idle_for_seconds: float) -> float:
    """How long to wait before reading the log again: quick while the chat is busy, slow when it is not."""
    return BUSY_POLL_SECONDS if idle_for_seconds < BUSY_WINDOW_SECONDS else IDLE_POLL_SECONDS


def wait(seconds: float) -> None:
    if not runtime.IS_WORKER:
        time.sleep(seconds)
        return
    import asyncio

    from pyodide.ffi import run_sync

    run_sync(asyncio.sleep(seconds))
