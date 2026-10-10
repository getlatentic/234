# SPDX-License-Identifier: AGPL-3.0-or-later
"""A person's wallet as an append-only journal (migrations/0011_wallet.sql): the balance is the signed sum
of the owner's entries, and nothing else holds it.

D1 has no interactive transactions, so no rule here reads and then writes (as in ledger.py). Each movement
is one INSERT ... SELECT whose WHERE holds the rule, and the rows it inserted say whether the caller won:

* no negative balance: a debit lands only while the owner's signed sum, taken in that same statement, covers
  it, so two debits that cannot both fit cannot both land;
* a frozen wallet pays nothing: the same debit requires the wallet row with `frozen = 0`;
* the balance cap: a `fund` lands only while the sum plus the amount stays within the cap;
* once per ref: UNIQUE (owner, kind, ref), so a webhook delivered twice or a retried call is answered by the
  entry the first one wrote, never by a second row.
"""

from dataclasses import dataclass
from typing import Any

from ..clock import Clock
from ..db import Db
from ..errors import DomainError
from ..ids import new_wallet_entry_id
from ..money import Kobo
from .settings import WalletSettings

CREDIT_KINDS = frozenset({"fund", "release", "refund", "withdraw_back", "adjust"})
DEBIT_KINDS = frozenset({"spend", "withdraw", "adjust"})
CAPPED_KIND = "fund"
"""Only money coming in from outside is capped: a release, refund or failed withdrawal gives back what the
wallet already held, and refusing it would lose that money."""

BALANCE_SQL = "(SELECT COALESCE(SUM(sign * amount_kobo), 0) FROM wallet_entry WHERE owner = ?)"
_INSERT = (
    "INSERT INTO wallet_entry (id, owner, kind, sign, amount_kobo, ref, quote_id, created_at) "
    "SELECT ?, ?, ?, ?, ?, ?, ?, ? "
)
_ON_CONFLICT = " ON CONFLICT (owner, kind, ref) DO NOTHING"


@dataclass(frozen=True)
class Entry:
    seq: int
    id: str
    owner: str
    kind: str
    sign: int
    amount_kobo: Kobo
    ref: str
    quote_id: str | None
    created_at: int

    @property
    def signed_kobo(self) -> Kobo:
        return self.sign * self.amount_kobo


def entry_of(row: dict[str, Any]) -> Entry:
    return Entry(
        seq=row["seq"],
        id=row["id"],
        owner=row["owner"],
        kind=row["kind"],
        sign=row["sign"],
        amount_kobo=row["amount_kobo"],
        ref=row["ref"],
        quote_id=row["quote_id"],
        created_at=row["created_at"],
    )


def _assert_amount(amount: Kobo) -> None:
    if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
        raise DomainError("INVALID_INPUT", "A wallet amount is a positive whole number of kobo.")


class Journal:
    def __init__(self, db: Db, clock: Clock, settings: WalletSettings) -> None:
        self._db = db
        self._clock = clock
        self.settings = settings

    def _open_statement(self, owner: str) -> tuple[str, tuple[Any, ...]]:
        return (
            "INSERT INTO wallet (owner, frozen, created_at) VALUES (?, 0, ?) ON CONFLICT (owner) DO NOTHING",
            (owner, self._clock.now()),
        )

    async def open(self, owner: str) -> None:
        sql, params = self._open_statement(owner)
        await self._db.execute(sql, *params)

    async def set_frozen(self, owner: str, frozen: bool) -> bool:
        """True when the wallet exists and is now in the state asked for."""
        changed = await self._db.execute(
            "UPDATE wallet SET frozen = ? WHERE owner = ?", 1 if frozen else 0, owner
        )
        return changed == 1

    async def is_frozen(self, owner: str) -> bool:
        row = await self._db.row("SELECT frozen FROM wallet WHERE owner = ?", owner)
        return bool(row and row["frozen"])

    async def credit(
        self, owner: str, kind: str, amount: Kobo, ref: str, quote_id: str | None = None
    ) -> Entry | None:
        """The entry for this ref, written now or by an earlier call; None when the cap refused it."""
        if kind not in CREDIT_KINDS:
            raise ValueError(f"{kind} is not a credit")
        _assert_amount(amount)
        now, cap = self._clock.now(), self.settings.balance_cap_kobo
        results = await self._db.batch(
            [
                self._open_statement(owner),
                (
                    f"{_INSERT}WHERE (? <> '{CAPPED_KIND}' OR {BALANCE_SQL} + ? <= ?){_ON_CONFLICT}",
                    (
                        new_wallet_entry_id(),
                        owner,
                        kind,
                        1,
                        amount,
                        ref,
                        quote_id,
                        now,
                        kind,
                        owner,
                        amount,
                        cap,
                    ),
                ),
            ]
        )
        return await self._landed(results[1].changes, owner, kind, amount, ref)

    async def debit(
        self, owner: str, kind: str, amount: Kobo, ref: str, quote_id: str | None = None
    ) -> Entry | None:
        """The entry for this ref, written now or by an earlier call; None when the wallet is missing, frozen
        or does not cover the amount."""
        if kind not in DEBIT_KINDS:
            raise ValueError(f"{kind} is not a debit")
        _assert_amount(amount)
        changed = await self._db.execute(
            f"{_INSERT}WHERE EXISTS (SELECT 1 FROM wallet WHERE owner = ? AND frozen = 0) "
            f"AND {BALANCE_SQL} >= ?{_ON_CONFLICT}",
            new_wallet_entry_id(),
            owner,
            kind,
            -1,
            amount,
            ref,
            quote_id,
            self._clock.now(),
            owner,
            owner,
            amount,
        )
        return await self._landed(changed, owner, kind, amount, ref)

    async def _landed(self, changed: int, owner: str, kind: str, amount: Kobo, ref: str) -> Entry | None:
        entry = await self.entry(owner, kind, ref)
        if entry is None or changed == 1:
            return entry
        if entry.amount_kobo != amount:
            raise DomainError(
                "WALLET_REF_CONFLICT",
                f"The {kind} {ref} was already recorded for another amount, so nothing was changed.",
            )
        return entry

    async def entry(self, owner: str, kind: str, ref: str) -> Entry | None:
        row = await self._db.row(
            "SELECT * FROM wallet_entry WHERE owner = ? AND kind = ? AND ref = ?", owner, kind, ref
        )
        return entry_of(row) if row else None

    async def balance(self, owner: str) -> Kobo:
        row = await self._db.row(f"SELECT {BALANCE_SQL} AS balance", owner)
        return int(row["balance"]) if row else 0

    async def history(self, owner: str, limit: int = 50) -> list[Entry]:
        """The owner's entries, newest first."""
        rows = await self._db.rows(
            "SELECT * FROM wallet_entry WHERE owner = ? ORDER BY seq DESC LIMIT ?", owner, max(limit, 0)
        )
        return [entry_of(row) for row in rows]
