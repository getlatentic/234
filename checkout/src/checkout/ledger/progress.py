# SPDX-License-Identifier: AGPL-3.0-or-later
"""What happens to a quote after it is made: its progress, its state, and the step a provider call holds.

A settled quote changes state only to `reversed`, and a reversed one never again: a trigger holds it
(migrations/0016_quote_reversed.sql).

Progress: `json_patch` merges in SQL, so two writers touching different keys both land.
"""

import json
from typing import Any

from ..db import Statement
from ..errors import DomainError
from .records import ENDED_STATES, Quote
from .store import QuoteStore


class ProgressWrites(QuoteStore):
    async def patch_progress(
        self, quote_id: str, patch: dict[str, Any], only_state: str | None = None
    ) -> Quote:
        """Merges into progress inside SQL (RFC 7396): a None value removes its key. With `only_state`
        the merge happens only while the quote is in that state."""
        await self._db.execute(
            "UPDATE quotes SET progress = json_patch(progress, ?) "
            "WHERE id = ? AND owner = ? AND (? IS NULL OR state = ?)",
            json.dumps(patch),
            quote_id,
            self.owner(),
            only_state,
            only_state,
        )
        return await self._must_get(quote_id)

    async def set_progress_once(self, quote_id: str, key: str, value: Any) -> bool:
        """Writes progress[key] only if it is not set yet; true when this caller wrote it, so of any
        number of racing callers exactly one gets to decide the value."""
        changed = await self._db.execute(
            "UPDATE quotes SET progress = json_patch(progress, json_object(?, json(?))) "
            "WHERE id = ? AND owner = ? AND json_extract(progress, ?) IS NULL",
            key,
            json.dumps(value),
            quote_id,
            self.owner(),
            f"$.{key}",
        )
        return changed == 1

    async def transition(
        self,
        quote_id: str,
        from_states: tuple[str, ...],
        to: str,
        patch: dict[str, Any] | None = None,
    ) -> Quote:
        """Moves a quote between states; asking for the state it is already in is a no-op."""
        marks = ", ".join("?" for _ in from_states)
        ended_at = self._clock.now() if to in ENDED_STATES else None
        changed = await self._db.execute(
            f"UPDATE quotes SET state = ?, settled_at = COALESCE(?, settled_at), "
            f"progress = json_patch(progress, ?) WHERE id = ? AND owner = ? AND state IN ({marks})",
            to,
            ended_at,
            json.dumps(patch or {}),
            quote_id,
            self.owner(),
            *from_states,
        )
        quote = await self._must_get(quote_id)
        if changed == 0 and quote.state != to:
            raise DomainError(
                "QUOTE_NOT_OPEN", f"This quote is {quote.state}, not {' or '.join(from_states)}."
            )
        return quote

    async def reverse(
        self, quote_id: str, patch: dict[str, Any], alongside: list[Statement]
    ) -> tuple[Quote, bool]:
        """Ends a delivered quote as reversed; true when this caller moved it. `alongside` runs after the
        UPDATE in the same batch, so what the reversal owes lands with it or not at all."""
        results = await self._db.batch(
            [
                (
                    "UPDATE quotes SET state = 'reversed', settled_at = ?, "
                    "progress = json_patch(progress, ?) WHERE id = ? AND owner = ? AND state = 'settled'",
                    (self._clock.now(), json.dumps(patch), quote_id, self.owner()),
                ),
                *alongside,
            ]
        )
        return await self._must_get(quote_id), results[0].changes == 1

    async def acquire_step(
        self, quote_id: str, stale_after_ms: int, patch: dict[str, Any] | None = None
    ) -> bool:
        """True when this caller may talk to a provider now; false while another call is doing so.
        `patch` is merged in the same statement, so the caller's own marker lands with the lock."""
        now = self._clock.now()
        changed = await self._db.execute(
            "UPDATE quotes SET progress = json_patch(json_patch(progress, ?), json_object('inFlightSince', "
            "?)) "
            "WHERE id = ? AND owner = ? AND (json_extract(progress, '$.inFlightSince') IS NULL "
            "OR ? - json_extract(progress, '$.inFlightSince') >= ?)",
            json.dumps(patch or {}),
            now,
            quote_id,
            self.owner(),
            now,
            stale_after_ms,
        )
        return changed == 1
