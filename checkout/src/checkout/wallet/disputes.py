# SPDX-License-Identifier: AGPL-3.0-or-later
"""A chargeback on a card top-up (docs/wallet.md, "Disputes"; migrations/0015_wallet_dispute.sql).

Bachs takes the disputed amount from 234 when the dispute opens, so 234 holds it in the wallet the top-up
paid: a `dispute` entry keyed by the dispute, of what the wallet has, up to the disputed amount (never below
₦0). While the dispute is open the owner cannot withdraw (withdrawal_block.py), and a wallet the hold could
not cover is frozen until it ends (freeze.py). Won or closed, the hold is written back as `dispute_back`,
exactly what it took; lost or prevented, the hold stays, and what it could not cover is 234's loss, written
off on the dispute for the reconciliation. Either way the block and the freeze are lifted. Bachs' fee is
234's.

Events come more than once and in any order, so 234 acts on the status each one carries, never on its type,
and every event is one batch, as D1 has no interactive transactions: the dispute opened if it is not (the row,
then the hold, the block and the freeze, each requiring the row still open, so a late `created` after a
decision does nothing), then, for a final status, the decision (`open → final` once, then the write-back and
the lifts, each requiring the decided row, so a repeat finds them done). A dispute that names no top-up's
charge (a charge is kept only once its collection is credited), another currency, or more than the top-up's
amount opens nothing and is audited. 234's Bachs account takes nothing but top-ups, so an unknown charge is
one whose collection is not credited yet: it is `Refused(UNKNOWN)`, which the hook answers so that Bachs
delivers the dispute again (provider_hooks/bachs.py)."""

from dataclasses import dataclass
from typing import Any

from ..audit import Audit
from ..bachs.api import NGN
from ..bachs.disputes import KEPT_BY_234, LOST_BY_234, Dispute
from ..clock import Clock
from ..db import Db, Statement, StatementResult
from ..ids import new_wallet_entry_id
from ..money import Kobo

REASON = "dispute"
UNKNOWN = "unknown"
OPENED, FROZE, DECIDED = 0, 3, 4
"""Where the batch's row, freeze and decision statements stand (`_statements`), to say what this event did."""


def _in(states: frozenset[str]) -> str:
    return ", ".join(f"'{state}'" for state in sorted(states))


_THIS_OPEN = "FROM wallet_dispute AS d WHERE d.id = ? AND d.state = 'open'"
_BALANCE = "(SELECT COALESCE(SUM(e.sign * e.amount_kobo), 0) FROM wallet_entry AS e WHERE e.owner = d.owner)"
_HELD = (
    "COALESCE((SELECT h.amount_kobo FROM wallet_entry AS h WHERE h.owner = {d}.owner AND h.kind = 'dispute' "
    "AND h.ref = {d}.id), 0)"
)
_OPEN = (
    "INSERT INTO wallet_dispute (id, owner, topup_id, charge_id, amount_kobo, state, created_at) "
    "SELECT ?, t.owner, t.id, t.charge_id, ?, 'open', ? FROM wallet_topup AS t "
    "WHERE t.charge_id = ? AND ? = 'NGN' AND ? BETWEEN 1 AND t.amount_kobo "
    "ON CONFLICT (id) DO NOTHING"
)
_HOLD = (
    "INSERT INTO wallet_entry (id, owner, kind, sign, amount_kobo, ref, quote_id, created_at) "
    f"SELECT ?, d.owner, 'dispute', -1, MIN(d.amount_kobo, {_BALANCE}), d.id, NULL, ? {_THIS_OPEN} "
    f"AND {_BALANCE} > 0 "
    f"AND NOT EXISTS (SELECT 1 FROM wallet_freeze AS f WHERE f.owner = d.owner AND f.reason = '{REASON}' "
    "AND f.ref = d.id) "
    "ON CONFLICT (owner, kind, ref) DO NOTHING"
)
_BLOCK = (
    "INSERT INTO wallet_withdrawal_block (owner, reason, ref, created_at) "
    f"SELECT d.owner, '{REASON}', d.id, ? {_THIS_OPEN} "
    "ON CONFLICT (owner, reason, ref) DO NOTHING"
)
_FREEZE = (
    "INSERT INTO wallet_freeze (owner, reason, ref, created_at) "
    f"SELECT d.owner, '{REASON}', d.id, ? {_THIS_OPEN} AND {_HELD.format(d='d')} < d.amount_kobo "
    "ON CONFLICT (owner, reason, ref) DO NOTHING"
)
_DECIDE = (
    "UPDATE wallet_dispute SET state = ?, decided_at = ?, written_off_kobo = "
    f"CASE WHEN ? IN ({_in(LOST_BY_234)}) THEN amount_kobo - {_HELD.format(d='wallet_dispute')} ELSE 0 END "
    "WHERE id = ? AND state = 'open'"
)
_GIVE_BACK = (
    "INSERT INTO wallet_entry (id, owner, kind, sign, amount_kobo, ref, quote_id, created_at) "
    "SELECT ?, h.owner, 'dispute_back', 1, h.amount_kobo, h.ref, NULL, ? FROM wallet_entry AS h "
    "WHERE h.kind = 'dispute' AND h.ref = ? "
    "AND EXISTS (SELECT 1 FROM wallet_dispute AS d WHERE d.id = h.ref AND d.owner = h.owner "
    f"AND d.state IN ({_in(KEPT_BY_234)})) "
    "ON CONFLICT (owner, kind, ref) DO NOTHING"
)


def _lift(table: str) -> str:
    return (
        f"UPDATE {table} SET lifted_at = ? WHERE reason = '{REASON}' AND ref = ? AND lifted_at IS NULL "
        f"AND EXISTS (SELECT 1 FROM wallet_dispute AS d WHERE d.id = ? AND d.owner = {table}.owner "
        "AND d.state <> 'open')"
    )


@dataclass(frozen=True)
class Refused:
    reason: str


@dataclass(frozen=True)
class DisputeRecord:
    id: str
    owner: str
    topup_id: str
    amount_kobo: Kobo
    state: str
    held_kobo: Kobo
    written_off_kobo: Kobo


def record_of(row: dict[str, Any]) -> DisputeRecord:
    return DisputeRecord(
        row["id"], row["owner"], row["topup_id"], row["amount_kobo"], row["state"], row["held_kobo"],
        row["written_off_kobo"],
    )  # fmt: skip


class Disputes:
    def __init__(self, db: Db, clock: Clock, audit: Audit) -> None:
        self._db = db
        self._clock = clock
        self._audit = audit

    async def settle(self, dispute: Dispute) -> DisputeRecord | Refused:
        """The dispute as it stands after this event, or why it was refused."""
        if dispute.dispute_id is None or dispute.charge_id is None or dispute.amount_kobo is None:
            return self._refused("shape", dispute)
        results = await self._db.batch(self._statements(dispute, dispute.dispute_id))
        found = await self.get(dispute.dispute_id)
        if found is None:
            return self._refused(await self._why_not(dispute), dispute)
        self._log(found, results)
        return found

    async def _why_not(self, dispute: Dispute) -> str:
        """Why a dispute opened nothing; the rules themselves are held by the statement that opens it."""
        if dispute.currency != NGN:
            return "currency"
        topup = await self._db.row(
            "SELECT amount_kobo FROM wallet_topup WHERE charge_id = ?", dispute.charge_id
        )
        return UNKNOWN if topup is None else "amount"

    def _statements(self, dispute: Dispute, dispute_id: str) -> list[Statement]:
        now, amount = self._clock.now(), dispute.amount_kobo
        opening: list[Statement] = [
            (_OPEN, (dispute_id, amount, now, dispute.charge_id, dispute.currency, amount)),
            (_HOLD, (new_wallet_entry_id(), now, dispute_id)),
            (_BLOCK, (now, dispute_id)),
            (_FREEZE, (now, dispute_id)),
        ]
        decision = dispute.decision
        if decision is None:
            return opening
        return [
            *opening,
            (_DECIDE, (decision, now, decision, dispute_id)),
            (_GIVE_BACK, (new_wallet_entry_id(), now, dispute_id)),
            (_lift("wallet_withdrawal_block"), (now, dispute_id, dispute_id)),
            (_lift("wallet_freeze"), (now, dispute_id, dispute_id)),
        ]

    def _log(self, found: DisputeRecord, results: list[StatementResult]) -> None:
        terms = {"dispute": found.id, "amount_kobo": found.amount_kobo, "held_kobo": found.held_kobo}
        if results[OPENED].changes == 1:
            self._audit.log("wallet.dispute.opened", topup=found.topup_id, **terms)
        if results[FROZE].changes == 1:
            self._audit.log("wallet.dispute.short", **terms)
        if len(results) > DECIDED and results[DECIDED].changes == 1:
            self._audit.log(
                "wallet.dispute.decided", state=found.state, written_off_kobo=found.written_off_kobo, **terms
            )

    def _refused(self, reason: str, dispute: Dispute) -> Refused:
        self._audit.log(
            "wallet.dispute.refused",
            reason=reason,
            dispute=(dispute.dispute_id or "")[:64],
            charge=(dispute.charge_id or "")[:64],
            amount_kobo=dispute.amount_kobo,
            currency=(dispute.currency or "")[:8],
            event_id=dispute.event_id,
        )
        return Refused(reason)

    async def get(self, dispute_id: str) -> DisputeRecord | None:
        row = await self._db.row(
            f"SELECT d.*, {_HELD.format(d='d')} AS held_kobo FROM wallet_dispute AS d WHERE d.id = ?",
            dispute_id,
        )
        return record_of(row) if row else None
