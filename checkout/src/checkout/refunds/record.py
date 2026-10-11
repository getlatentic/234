# SPDX-License-Identifier: AGPL-3.0-or-later
"""A refund as 234 keeps it (migrations/0019_quote_refund.sql), with the connector of its quote: that
connector's Paystack took the payment, and so refunds it."""

from dataclasses import dataclass
from typing import Any

from ..money import Kobo

UNDECIDED = ("sent", "needs_attention")
UNDECIDED_SQL = ", ".join(f"'{state}'" for state in UNDECIDED)
READ = "SELECT r.*, q.connector FROM quote_refund AS r JOIN quotes AS q ON q.id = r.quote_id "


@dataclass(frozen=True)
class Refund:
    quote_id: str
    owner: str
    amount_kobo: Kobo
    transaction_reference: str
    transaction_id: int | None
    state: str
    refund_id: int | None
    refund_status: str | None
    why: str | None
    sending_since: int | None
    created_at: int
    decided_at: int | None
    connector: str


def refund_of(row: dict[str, Any]) -> Refund:
    return Refund(**{name: row[name] for name in Refund.__dataclass_fields__})
