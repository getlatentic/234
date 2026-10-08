# SPDX-License-Identifier: AGPL-3.0-or-later
"""The host's log lines: JSON, one per record, with where it comes from (turns/trace.py), and scrubbed
whatever the caller passed (docs/logs.md). One filter does the scrubbing and the context; a formatter writes
the line.

What is removed is what the connectors' audit log removes (checkout/audit.py: keys, and digit runs of seven or
more shortened to their first four and last three), and what the summariser is never shown (turns/compaction/
scrub.py: links, tokens, one-time codes, long secrets, card numbers). It is applied to the message, to a
traceback and to every text field, so an exception that carries an account number logs without it.
"""

import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

from . import trace
from .compaction.scrub import scrubbed

_LINK_PRIVATE = re.compile(r"(?<=://)[^/\s\"]*@|[?#][^\s\"]*")
_LONG_DIGITS = re.compile(r"(?<![A-Za-z0-9])\d{7,}(?![A-Za-z0-9])")
FIELDS = "fields"
_plain = logging.Formatter()


def _mask(digits: str) -> str:
    return f"{digits[:4]}{'*' * (len(digits) - 7)}{digits[-3:]}"


def scrub(text: str) -> str:
    """`text` without what a log line must never hold; a link keeps its origin and path, not its credentials,
    query or fragment."""
    kept = _LINK_PRIVATE.sub("", text)
    return _LONG_DIGITS.sub(lambda m: _mask(m.group()), scrubbed(kept, links=True))


def event(log: logging.Logger, name: str, **fields: Any) -> None:
    """One structured line: its name, and numbers and short words (a string among them is scrubbed)."""
    log.info(name, extra={FIELDS: fields})


class ScrubFilter(logging.Filter):
    """Scrubs the record and says where it comes from. It runs on the handler, so every record that reaches
    the console is scrubbed, Django's and the libraries' as well as ours."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg, record.args = scrub(record.getMessage()), None
        if record.exc_info:
            record.exc_text = scrub(_plain.formatException(record.exc_info))
            record.exc_info = None
        if record.stack_info:
            record.stack_info = scrub(record.stack_info)
        fields = getattr(record, FIELDS, None) or {}
        setattr(record, FIELDS, {k: scrub(v) if isinstance(v, str) else v for k, v in fields.items()})
        record.trace = trace.current()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        where = getattr(record, "trace", None) or trace.current()
        line: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.msg if isinstance(record.msg, str) else str(record.msg),
        }
        line.update(
            {k: v for k, v in (("chat", where.chat), ("owner", where.owner), ("task", where.task)) if v}
        )
        line.update(getattr(record, FIELDS, None) or {})
        if record.exc_text:
            line["exc"] = record.exc_text
        if record.stack_info:
            line["stack"] = record.stack_info
        return json.dumps(line, ensure_ascii=False)
