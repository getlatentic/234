# SPDX-License-Identifier: AGPL-3.0-or-later
"""What 234's own records say it owes (docs/wallet.md, "Reconciliation"), read from D1 in one round trip.

* owed: every wallet's balance together, the signed sum of the whole journal. Holds on quotes not yet paid are
  already out of it, as they are out of each balance.
* withdrawing: withdrawals whose money left the wallets but that Paystack has not settled; it is still in
  Paystack's balance, so it is shown, not taken from the gap.
* disputes: how many there were (each cost 234 Bachs' $15), how many are open and for how much, and what lost
  or prevented ones could not hold, written off as 234's loss."""

from dataclasses import dataclass

from ..db import Db
from ..money import Kobo

_BOOKS = (
    "SELECT (SELECT COALESCE(SUM(sign * amount_kobo), 0) FROM wallet_entry) AS owed, "
    "(SELECT COALESCE(SUM(amount_kobo), 0) FROM wallet_withdrawal WHERE state = 'sent') AS withdrawing, "
    "(SELECT COUNT(*) FROM wallet_dispute) AS disputes, "
    "(SELECT COUNT(*) FROM wallet_dispute WHERE state = 'open') AS open_disputes, "
    "(SELECT COALESCE(SUM(amount_kobo), 0) FROM wallet_dispute WHERE state = 'open') AS open_disputed, "
    "(SELECT COALESCE(SUM(written_off_kobo), 0) FROM wallet_dispute) AS written_off"
)


@dataclass(frozen=True)
class Books:
    owed_kobo: Kobo
    withdrawing_kobo: Kobo
    disputes: int
    open_disputes: int
    open_disputed_kobo: Kobo
    written_off_kobo: Kobo


async def books_of(db: Db) -> Books:
    row = await db.row(_BOOKS)
    assert row is not None
    return Books(
        int(row["owed"]), int(row["withdrawing"]), int(row["disputes"]), int(row["open_disputes"]),
        int(row["open_disputed"]), int(row["written_off"]),
    )  # fmt: skip
