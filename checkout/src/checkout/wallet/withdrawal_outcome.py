# SPDX-License-Identifier: AGPL-3.0-or-later
"""What becomes of a withdrawal once its money is taken (docs/wallet.md, "Withdrawing"): the Paystack
transfer, sent with the withdrawal id as its reference, and the three outcomes.

* success settles it: `sent → succeeded`;
* failed, or reversed (a transfer that succeeded and came back), gives the money back: the state change and
  the `withdraw_back` entry are one batch, and the entry is written only for a withdrawal in that state, once
  (UNIQUE (owner, kind, ref)), for exactly what its `withdraw` entry took;
* anything else (pending, a one-time code, a timeout, a lost reply) leaves it `sent`, undecided, until a
  Paystack event or the minute re-check asks Paystack about its reference.

The reference never changes, so a withdrawal is never sent under another. It is sent again under the same
one only when Paystack has no transfer of that reference, Paystack never answered a send of it, and no other
caller is sending it now (`sending_since`, taken by one UPDATE)."""

from ..audit import Audit
from ..clock import Clock
from ..db import Db
from ..ids import new_wallet_entry_id
from ..paystack.api import PaystackApi, PaystackError, TransferOutcome, TransferRequest
from .withdrawal_record import GIVEN_BACK, UNDECIDED, Withdrawal, withdrawal_of

REASON = "234 wallet withdrawal"
SEND_STALE_MS = 30_000
RECHECK_AFTER_MS = 30_000
RECHECK_LIMIT = 50

_GIVEN_BACK_SQL = ", ".join(f"'{state}'" for state in GIVEN_BACK)
_WITHDRAW_BACK = (
    "INSERT INTO wallet_entry (id, owner, kind, sign, amount_kobo, ref, quote_id, created_at) "
    "SELECT ?, d.owner, 'withdraw_back', 1, d.amount_kobo, d.ref, NULL, ? FROM wallet_entry AS d "
    "JOIN wallet_withdrawal AS w ON w.id = d.ref AND w.owner = d.owner "
    f"WHERE d.kind = 'withdraw' AND d.ref = ? AND w.state IN ({_GIVEN_BACK_SQL}) "
    "ON CONFLICT (owner, kind, ref) DO NOTHING"
)
_DECIDE = (
    "UPDATE wallet_withdrawal SET state = ?, transfer_code = COALESCE(?, transfer_code), "
    "transfer_status = ?, decided_at = ?, sending_since = NULL WHERE id = ? AND state IN "
)
_CLAIM_SEND = (
    "UPDATE wallet_withdrawal SET sending_since = ? WHERE id = ? AND state = 'sent' "
    "AND transfer_code IS NULL AND (sending_since IS NULL OR sending_since <= ?)"
)
_EXPIRE = (
    "UPDATE wallet_withdrawal SET state = 'expired' WHERE state = 'open' AND expires_at <= ? "
    "AND NOT EXISTS (SELECT 1 FROM wallet_entry AS d WHERE d.owner = wallet_withdrawal.owner "
    "AND d.kind = 'withdraw' AND d.ref = wallet_withdrawal.id)"
)


class WithdrawalOutcomes:
    def __init__(self, db: Db, clock: Clock, paystack: PaystackApi, audit: Audit) -> None:
        self._db = db
        self._clock = clock
        self._paystack = paystack
        self._audit = audit

    async def get(self, withdrawal_id: str) -> Withdrawal | None:
        """The one read that names no owner: a Paystack event names only the reference."""
        row = await self._db.row("SELECT * FROM wallet_withdrawal WHERE id = ?", withdrawal_id)
        return withdrawal_of(row) if row else None

    async def _fresh(self, withdrawal: Withdrawal) -> Withdrawal:
        return await self.get(withdrawal.id) or withdrawal

    async def send(self, withdrawal: Withdrawal) -> Withdrawal:
        """Sends the transfer of a withdrawal whose money is taken; the caller holds `sending_since`."""
        request = TransferRequest(withdrawal.amount_kobo, withdrawal.recipient_code, withdrawal.id, REASON)
        try:
            outcome = await self._paystack.initiate_transfer(request)
        except PaystackError as error:
            return await self._refused(withdrawal, error)
        self._audit.log("withdrawal.sent", withdrawal=withdrawal.id, status=outcome.status)
        return await self.record(withdrawal, outcome)

    async def _refused(self, withdrawal: Withdrawal, error: PaystackError) -> Withdrawal:
        """A refusal that may not have reached Paystack leaves it undecided. One that did is asked about
        once more, in case Paystack already holds a transfer of this reference, before it fails."""
        if error.retryable:
            return await self._let_go(withdrawal, "no answer")
        try:
            found = await self._find(withdrawal)
        except PaystackError:
            return await self._let_go(withdrawal, "no answer")
        if found is not None:
            return await self.record(withdrawal, found)
        return await self._decide(withdrawal, "failed", None, "refused")

    async def _let_go(self, withdrawal: Withdrawal, why: str) -> Withdrawal:
        await self._db.execute(
            f"UPDATE wallet_withdrawal SET sending_since = NULL WHERE id = ? AND state = '{UNDECIDED}'",
            withdrawal.id,
        )
        self._audit.log("withdrawal.undecided", withdrawal=withdrawal.id, why=why)
        return await self._fresh(withdrawal)

    async def _find(self, withdrawal: Withdrawal) -> TransferOutcome | None:
        """Paystack's transfer of this reference, or None when it has none. A call that may not have
        reached Paystack raises."""
        try:
            return await self._paystack.verify_transfer(withdrawal.id)
        except PaystackError as error:
            if error.retryable:
                raise
            return None

    async def record(self, withdrawal: Withdrawal, outcome: TransferOutcome) -> Withdrawal:
        """What Paystack said about the transfer, written only while the withdrawal is undecided (or, for
        a reversal, succeeded)."""
        if outcome.reference != withdrawal.id or outcome.amount_kobo != withdrawal.amount_kobo:
            self._audit.log(
                "withdrawal.mismatch",
                withdrawal=withdrawal.id,
                amount_kobo=outcome.amount_kobo,
                expected_kobo=withdrawal.amount_kobo,
            )
            return await self._let_go(withdrawal, "mismatch")
        match outcome.status:
            case "success":
                return await self._decide(withdrawal, "succeeded", outcome.transfer_code, "success")
            case "failed" | "reversed":
                return await self._decide(withdrawal, outcome.status, outcome.transfer_code, outcome.status)
            case status:
                return await self._undecided(withdrawal, outcome.transfer_code, status)

    async def _undecided(self, withdrawal: Withdrawal, transfer_code: str, status: str) -> Withdrawal:
        await self._db.execute(
            "UPDATE wallet_withdrawal SET transfer_code = ?, transfer_status = ?, sending_since = NULL "
            f"WHERE id = ? AND state = '{UNDECIDED}'",
            transfer_code,
            status,
            withdrawal.id,
        )
        self._audit.log("withdrawal.undecided", withdrawal=withdrawal.id, why=status)
        return await self._fresh(withdrawal)

    async def _decide(
        self, withdrawal: Withdrawal, state: str, transfer_code: str | None, status: str
    ) -> Withdrawal:
        """The decision and, for a transfer that failed or came back, the money back, in one batch."""
        now = self._clock.now()
        leaving = "('sent', 'succeeded')" if state == "reversed" else f"('{UNDECIDED}')"
        results = await self._db.batch(
            [
                (f"{_DECIDE}{leaving}", (state, transfer_code, status, now, withdrawal.id)),
                (_WITHDRAW_BACK, (new_wallet_entry_id(), now, withdrawal.id)),
            ]
        )
        if results[0].changes == 1:
            self._audit.log(
                f"withdrawal.{state}", withdrawal=withdrawal.id, amount_kobo=withdrawal.amount_kobo
            )
        return await self._fresh(withdrawal)

    async def recheck(self, withdrawal_id: str) -> Withdrawal | None:
        """Asks Paystack about an undecided (or succeeded) withdrawal's reference and records the answer.
        A transfer Paystack never had is sent, under the same reference, by whoever takes the send."""
        withdrawal = await self.get(withdrawal_id)
        if withdrawal is None or withdrawal.state not in (UNDECIDED, "succeeded"):
            return withdrawal
        try:
            found = await self._find(withdrawal)
        except PaystackError:
            return withdrawal
        if found is not None:
            return await self.record(withdrawal, found)
        if withdrawal.state == UNDECIDED and await self._take_send(withdrawal):
            return await self.send(await self._fresh(withdrawal))
        return withdrawal

    async def _take_send(self, withdrawal: Withdrawal) -> bool:
        now = self._clock.now()
        return await self._db.execute(_CLAIM_SEND, now, withdrawal.id, now - SEND_STALE_MS) == 1

    async def undecided_ids(self) -> list[str]:
        """Withdrawals still undecided a while after the person pressed Withdraw, oldest first."""
        rows = await self._db.rows(
            f"SELECT id FROM wallet_withdrawal WHERE state = '{UNDECIDED}' AND name_confirmed_at < ? "
            "ORDER BY name_confirmed_at LIMIT ?",
            self._clock.now() - RECHECK_AFTER_MS,
            RECHECK_LIMIT,
        )
        return [row["id"] for row in rows]

    async def expire_due(self) -> int:
        """Open withdrawals past their time, now expired; how many. None of them ever took money."""
        return await self._db.execute(_EXPIRE, self._clock.now())
