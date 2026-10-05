# SPDX-License-Identifier: AGPL-3.0-or-later
"""MCP events: an ending reaches only its owner's subscriptions, a callback answers the challenge before it
is kept, an event is signed and sent once, and a 410 ends the subscription."""

from tools.mutations.model import SRC, Mutation

EVENTS = ["tests/test_events.py"]

MUTATIONS: list[Mutation] = [
    Mutation(
        "a quote's ending reaches only its owner's subscriptions",
        "migrations/0006_events.sql",
        "WHERE s.owner = NEW.owner AND s.connector",
        "WHERE s.connector",
        EVENTS,
    ),
    Mutation(
        "a callback answers the challenge before it is kept",
        f"{SRC}/events/service.py",
        "        if not await self._subscriptions.exists(asked.id):",
        "        if False:",
        EVENTS,
    ),
    Mutation(
        "the challenge must be echoed exactly",
        f"{SRC}/events/callbacks.py",
        "    if not isinstance(echoed, str) or not hmac.compare_digest(echoed, challenge):",
        "    if False:",
        EVENTS,
    ),
    Mutation(
        "one sender a row: two drains never send one event twice",
        f"{SRC}/events/delivery.py",
        "        return changed == 1",
        "        return True",
        EVENTS,
    ),
    Mutation(
        "events are signed over id, timestamp and body",
        f"{SRC}/events/signing.py",
        '    signed = f"{message_id}.{timestamp}.{body}".encode()',
        "    signed = body.encode()",
        EVENTS,
    ),
    Mutation(
        "a 410 ends the subscription",
        f"{SRC}/events/delivery.py",
        '            await self._db.execute("DELETE FROM event_subscriptions WHERE id = ?", '
        'row["subscription_id"])',
        "            pass",
        EVENTS,
    ),
    Mutation(
        "a callback must be HTTPS on a public host name",
        f"{SRC}/events/callbacks.py",
        '    if parts.scheme != "https" or not host or "." not in host or is_address or host in LOOPBACK:',
        "    if False:",
        EVENTS,
    ),
]
