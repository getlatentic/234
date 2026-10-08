# SPDX-License-Identifier: AGPL-3.0-or-later
"""The audit log: one JSON line per event, keys removed and long digit runs masked whatever the
caller passed. Sinks are plain callables, so a Worker prints, a test collects."""

import hashlib
import json
import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from .clock import Clock, SystemClock
from .mask import mask_phone
from .owner import current_owner, current_task

_KEY_LIKE = re.compile(r"\b(?:sk_(?:test|live)_|pk_(?:test|live)_|SK_|PK_)[A-Za-z0-9]+")
_LONG_DIGITS = re.compile(r"(?<![A-Za-z0-9])\d{7,}(?![A-Za-z0-9])")

Sink = Callable[[str], None]


def redact_keys(value: str) -> str:
    return _KEY_LIKE.sub("[redacted-key]", value)


def scrub(value: str) -> str:
    return _LONG_DIGITS.sub(lambda m: mask_phone(m.group()), redact_keys(value))


class Audit:
    def __init__(self, sinks: list[Sink], clock: Clock | None = None) -> None:
        self._sinks = sinks
        self._clock = clock or SystemClock()

    def log(self, event: str, **fields: Any) -> None:
        stamp = datetime.fromtimestamp(self._clock.now() / 1000, UTC)
        entry: dict[str, Any] = {
            "ts": stamp.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "event": event,
        }
        owner, task = current_owner(), current_task()
        if owner:
            entry["owner"] = hashlib.sha256(owner.encode()).hexdigest()[:12]
        if task:
            entry["task"] = task
        entry.update({k: scrub(v) if isinstance(v, str) else v for k, v in fields.items() if v is not None})
        line = json.dumps(entry, ensure_ascii=False)
        for sink in self._sinks:
            sink(line)


def print_sink(line: str) -> None:
    print(line, flush=True)
