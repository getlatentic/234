# SPDX-License-Identifier: AGPL-3.0-or-later
"""The wallet card's picture of a wallet: the balance and the latest entries in plain words, read from the
journal and never from what the model said."""

from datetime import UTC, datetime
from typing import Any

from ..db import Db
from ..money import Kobo, format_naira
from .journal import Entry, Journal

RECENT = 5
WORDS = {
    "fund": "Added",
    "release": "Returned",
    "refund": "Returned",
    "withdraw": "Withdrawn",
    "withdraw_back": "Returned",
    "adjust": "Adjusted",
}
PAID_FOR = {"airtime": "Paid airtime", "data": "Paid data"}


def signed_naira(kobo: Kobo) -> str:
    return f"+{format_naira(kobo)}" if kobo > 0 else format_naira(kobo)


def iso(at_ms: int) -> str:
    return datetime.fromtimestamp(at_ms / 1000, UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


class WalletView:
    def __init__(self, journal: Journal, db: Db) -> None:
        self.journal = journal
        self._db = db

    async def of(self, owner: str) -> dict[str, Any]:
        balance = await self.journal.balance(owner)
        recent = await self.journal.history(owner, RECENT)
        kinds = await self._quote_kinds(owner, recent)
        return {
            "balanceKobo": balance,
            "balance": format_naira(balance),
            "frozen": await self.journal.is_frozen(owner),
            "entries": [self._line(entry, kinds) for entry in recent],
        }

    async def _quote_kinds(self, owner: str, entries: list[Entry]) -> dict[str, str]:
        ids = sorted({entry.quote_id for entry in entries if entry.quote_id})
        if not ids:
            return {}
        marks = ", ".join("?" for _ in ids)
        rows = await self._db.rows(
            f"SELECT id, kind FROM quotes WHERE owner = ? AND id IN ({marks})", owner, *ids
        )
        return {row["id"]: row["kind"] for row in rows}

    @staticmethod
    def _line(entry: Entry, kinds: dict[str, str]) -> dict[str, Any]:
        label = WORDS.get(entry.kind, "Paid")
        if entry.kind == "spend":
            label = PAID_FOR.get(kinds.get(entry.quote_id or "", ""), "Paid")
        return {
            "id": entry.id,
            "label": label,
            "amountKobo": entry.signed_kobo,
            "amount": signed_naira(entry.signed_kobo),
            "at": iso(entry.created_at),
        }
