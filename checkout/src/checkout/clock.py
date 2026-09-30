# SPDX-License-Identifier: AGPL-3.0-or-later
"""Time as the ledger reads it: epoch milliseconds, and the Africa/Lagos calendar day (UTC+1, no DST)."""

import time
from datetime import UTC, datetime, timedelta
from typing import Protocol

LAGOS_OFFSET_MS = 60 * 60 * 1000
DAY_MS = 24 * 60 * 60 * 1000
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


class Clock(Protocol):
    def now(self) -> int: ...


class SystemClock:
    def now(self) -> int:
        return int(time.time() * 1000)


def lagos_day_start(at: int) -> int:
    shifted = at + LAGOS_OFFSET_MS
    return shifted - (shifted % DAY_MS) - LAGOS_OFFSET_MS


def lagos_stamp(at: int) -> str:
    """YYYYMMDDHHMM in Africa/Lagos, the prefix VTpass requires on a request id."""
    moment = datetime.fromtimestamp(0, UTC) + timedelta(milliseconds=at + LAGOS_OFFSET_MS)
    return moment.strftime("%Y%m%d%H%M")


def format_lagos(at: int) -> str:
    moment = datetime.fromtimestamp(0, UTC) + timedelta(milliseconds=at + LAGOS_OFFSET_MS)
    return f"{moment.day} {MONTHS[moment.month - 1]} {moment.year}, {moment.hour:02d}:{moment.minute:02d} WAT"
