# SPDX-License-Identifier: AGPL-3.0-or-later
"""Corrections to a wallet by an operator (docs/wallet.md, "Corrections"): an `adjust` entry, keyed by the
correction id the operator chose, and its record in `wallet_adjustment`.

One batch, as D1 has no interactive transactions, and every rule in the WHERE of the statement it guards:

1. the `adjust` entry (ref = the correction id). A debit lands only from a wallet that is not frozen and
   whose balance covers it, as journal.py's debit does; a credit is not capped. It lands either for a new
   correction id at or below the two-operator threshold, or for a proposal of the same terms that another
   operator made;
2. `proposed → applied`, by an operator other than the proposer, only while that entry exists;
3. the record of a correction applied by one operator, only while that entry exists;
4. the record of a proposal: above the threshold, nothing moved, the owner's wallet exists.

A correction id is the record's key, so it is applied at most once, and a retry is answered with what the
first call recorded; the same id with other terms is refused."""

from ..audit import Audit
from ..clock import Clock
from ..db import Db
from ..errors import DomainError
from ..ids import new_wallet_entry_id
from ..metrics import REFUSED, REPEAT, WRITTEN
from ..money import Kobo, format_naira
from ..owner import acting_for
from .correction import Adjustment, Correction, adjustment_of
from .journal import BALANCE_SQL, Journal

_ENTRY = (
    "INSERT INTO wallet_entry (id, owner, kind, sign, amount_kobo, ref, quote_id, created_at) "
    "SELECT ?, ?, 'adjust', ?, ?, ?, NULL, ? "
    "WHERE EXISTS (SELECT 1 FROM wallet WHERE owner = ? AND (? = 1 OR frozen = 0)) "
    f"AND (? = 1 OR {BALANCE_SQL} >= ?) "
    "AND ((? <= ? AND NOT EXISTS (SELECT 1 FROM wallet_adjustment WHERE correction_id = ?)) "
    "OR EXISTS (SELECT 1 FROM wallet_adjustment AS a WHERE a.correction_id = ? AND a.state = 'proposed' "
    "AND a.owner = ? AND a.sign = ? AND a.amount_kobo = ? AND a.reason = ? AND a.proposed_by <> ?)) "
    "ON CONFLICT (owner, kind, ref) DO NOTHING"
)
_ENTRY_EXISTS = (
    "EXISTS (SELECT 1 FROM wallet_entry AS e WHERE e.owner = ? AND e.kind = 'adjust' AND e.ref = ?)"
)
_APPROVE = (
    "UPDATE wallet_adjustment SET state = 'applied', approved_by = ?, applied_at = ? "
    f"WHERE correction_id = ? AND state = 'proposed' AND proposed_by <> ? AND owner = ? AND {_ENTRY_EXISTS}"
)
_RECORD = (
    "INSERT INTO wallet_adjustment (correction_id, owner, sign, amount_kobo, reason, proposed_by, state, "
    "created_at, applied_at) SELECT ?, ?, ?, ?, ?, ?, ?, ?, ? WHERE "
)
_APPLIED = f"{_RECORD}{_ENTRY_EXISTS} ON CONFLICT (correction_id) DO NOTHING"
_PROPOSED = (
    f"{_RECORD}? > ? AND EXISTS (SELECT 1 FROM wallet WHERE owner = ?) ON CONFLICT (correction_id) DO NOTHING"
)


class Adjustments:
    def __init__(self, db: Db, clock: Clock, journal: Journal, audit: Audit) -> None:
        self._db = db
        self._clock = clock
        self.journal = journal
        self._audit = audit

    @property
    def threshold_kobo(self) -> Kobo:
        """Above this, a correction needs a second operator."""
        return self.journal.settings.adjust_two_operators_kobo

    async def get(self, correction_id: str) -> Adjustment | None:
        row = await self._db.row("SELECT * FROM wallet_adjustment WHERE correction_id = ?", correction_id)
        return adjustment_of(row) if row else None

    async def adjust(self, asked: Correction) -> tuple[Adjustment, bool]:
        """The correction as recorded, and whether this call moved the money; a refusal raises."""
        with acting_for(asked.owner):
            moved, proposed = await self._write(asked)
            found = await self.get(asked.correction_id)
            if found is None or found.terms() != asked.terms():
                raise await self._refuse(asked, found)
            if found.state == "applied":
                self._applied(asked, found, moved)
            elif proposed:
                self._log("wallet.adjust.proposed", asked)
            elif asked.operator != found.proposed_by:
                raise await self._refuse(asked, found)
            else:
                self._log("wallet.adjust.refused", asked, why="second_operator")
            return found, moved

    async def _write(self, asked: Correction) -> tuple[bool, bool]:
        """The batch; whether it wrote the entry, and whether it recorded a new proposal."""
        now, threshold = self._clock.now(), self.threshold_kobo
        cid, owner, sign, amount, reason, operator = (
            asked.correction_id, asked.owner, asked.sign, asked.amount_kobo, asked.reason, asked.operator,
        )  # fmt: skip
        entry = (
            new_wallet_entry_id(), owner, sign, amount, cid, now, owner, sign, sign, owner, amount,
            amount, threshold, cid, cid, owner, sign, amount, reason, operator,
        )  # fmt: skip
        record = (cid, owner, sign, amount, reason, operator)
        results = await self._db.batch(
            [
                (_ENTRY, entry),
                (_APPROVE, (operator, now, cid, operator, owner, owner, cid)),
                (_APPLIED, (*record, "applied", now, now, owner, cid)),
                (_PROPOSED, (*record, "proposed", now, None, amount, threshold, owner)),
            ]
        )
        return results[0].changes == 1, results[3].changes == 1

    def _applied(self, asked: Correction, found: Adjustment, moved: bool) -> None:
        self.journal.metrics.wallet("adjust", WRITTEN if moved else REPEAT, found.amount_kobo)
        if moved:
            self._log("wallet.adjust.applied", asked, proposed_by=found.proposed_by)

    async def _refuse(self, asked: Correction, found: Adjustment | None) -> DomainError:
        error = await self._why_not(asked, found)
        self.journal.metrics.wallet("adjust", REFUSED, asked.amount_kobo)
        self._log("wallet.adjust.refused", asked, why=error.code)
        return error

    async def _why_not(self, asked: Correction, found: Adjustment | None) -> DomainError:
        if found is not None and found.terms() != asked.terms():
            return DomainError(
                "CORRECTION_CONFLICT", "That correction id was used for other terms, so nothing was changed."
            )
        wallet = await self._db.row("SELECT frozen FROM wallet WHERE owner = ?", asked.owner)
        if wallet is None:
            return DomainError("WALLET_NONE", "This owner has no wallet. Nothing was changed.")
        if wallet["frozen"]:
            return DomainError("WALLET_FROZEN", "This wallet is frozen, so nothing can leave it.")
        balance = await self.journal.balance(asked.owner)
        return DomainError(
            "WALLET_SHORT",
            f"The wallet holds {format_naira(balance)}, less than {format_naira(asked.amount_kobo)}. "
            "Nothing was changed.",
        )

    def _log(self, event: str, asked: Correction, **fields: str) -> None:
        self._audit.log(
            event,
            correction=asked.correction_id,
            operator=asked.operator,
            reason=asked.reason,
            sign=asked.sign,
            amount_kobo=asked.amount_kobo,
            **fields,
        )
