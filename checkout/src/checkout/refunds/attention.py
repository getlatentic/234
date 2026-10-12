# SPDX-License-Identifier: AGPL-3.0-or-later
"""The refunds an operator must see (docs/wallet.md, "Refunds"): Paystack failed one, 234 refused one (the
payment did not match the quote), Paystack holds one until it has the payer's bank account
(`needs_attention`), or a quote has owed one for longer than the minute takes to open it. 234 cannot finish
any of these alone. They are listed at GET /ops/refunds and counted in the reconciliation report."""

from dataclasses import dataclass
from typing import Any

from ..db import Db
from ..money import Kobo
from .owed import owed_sql

NEEDING = ("needs_attention", "failed", "refused")
NOT_OPENED_AFTER_MS = 15 * 60_000
"""The minute opens an owed refund at once; one still unopened a quarter of an hour on is stuck."""
LIMIT = 200

_NEEDING_SQL = ", ".join(f"'{state}'" for state in NEEDING)
_ENDED = "COALESCE((SELECT MAX(e.at) FROM quote_events AS e WHERE e.quote_id = q.id), q.created_at)"
"""When the quote came to owe its refund: its latest event."""
_LISTED = (
    "SELECT r.quote_id, q.connector, r.amount_kobo, r.state, r.why, r.refund_id, r.refund_status, "
    "r.created_at, r.decided_at FROM quote_refund AS r JOIN quotes AS q ON q.id = r.quote_id "
    f"WHERE r.state IN ({_NEEDING_SQL}) "
    "UNION ALL "
    f"SELECT q.id, q.connector, q.amount_kobo, 'not_opened', NULL, NULL, NULL, {_ENDED}, NULL "
    f"FROM quotes AS q WHERE {owed_sql('q')} AND {_ENDED} <= ? "
    "AND NOT EXISTS (SELECT 1 FROM quote_refund AS r WHERE r.quote_id = q.id) "
    "ORDER BY 8 DESC LIMIT ?"
)


@dataclass(frozen=True)
class NeedingOperator:
    quote_id: str
    connector: str
    amount_kobo: Kobo
    state: str
    why: str | None
    refund_id: int | None
    refund_status: str | None
    since: int
    decided_at: int | None

    def view(self) -> dict[str, Any]:
        return {
            "quoteId": self.quote_id,
            "connector": self.connector,
            "amountKobo": self.amount_kobo,
            "state": self.state,
            "why": self.why,
            "paystackRefundId": self.refund_id,
            "paystackStatus": self.refund_status,
            "since": self.since,
            "decidedAt": self.decided_at,
        }


async def needing_operator(db: Db, now: int) -> list[NeedingOperator]:
    """Newest first, at most LIMIT."""
    rows = await db.rows(_LISTED, now - NOT_OPENED_AFTER_MS, LIMIT)
    return [_needing(row) for row in rows]


def _needing(row: dict[str, Any]) -> NeedingOperator:
    return NeedingOperator(
        row["quote_id"], row["connector"], row["amount_kobo"], row["state"], row["why"],
        row["refund_id"], row["refund_status"], row["created_at"], row["decided_at"],
    )  # fmt: skip


def summary(listed: list[NeedingOperator]) -> dict[str, Any]:
    """How many of each, and the money they hold back from payers."""
    counts = {state: 0 for state in (*NEEDING, "not_opened")}
    for refund in listed:
        counts[refund.state] += 1
    return {"count": len(listed), "amountKobo": sum(r.amount_kobo for r in listed), "byState": counts}
