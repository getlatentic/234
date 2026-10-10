# SPDX-License-Identifier: AGPL-3.0-or-later
"""Starting a withdrawal and approving it (docs/wallet.md, "Withdrawing").

Start: the bank and the account number the person typed on the wallet card, the account resolved by the
bank (the same lookup a transfer quote makes), and a Paystack recipient for it; then an `open` withdrawal.
Nothing is taken. The card is given the name the bank holds the account under and a token for this
withdrawal only.

Approve: the person confirms that name on the card and presses Withdraw. 234 knows no legal name for an
account (a sign-in gives an email and whatever name the person chose), so the name is matched by the person,
not by 234: the call carries the name the card showed, and it must be the resolved name, exactly. Then one
batch, as D1 has no interactive transactions:

1. the `withdraw` entry (ref = the withdrawal id), one INSERT whose WHERE holds every rule: the owner's own
   `open` withdrawal, not expired, of the amount the card showed, under the name the card showed; within
   the per-withdrawal cap; the owner's wallet not frozen and not blocked from withdrawing
   (withdrawal_block.py); the balance covering it; and today's withdrawals (each `withdraw` entry of the
   Lagos day that was not given back) plus this one within the daily cap;
2. `open → sent`, only while that entry exists.

Two withdrawals that cannot both fit cannot both land, and a repeated press finds the first. Only the call
that moved it to `sent` sends the transfer (withdrawal_outcome.py)."""

import hashlib
import hmac

from ..audit import Audit
from ..clock import Clock, lagos_day_start
from ..db import Db
from ..errors import DomainError
from ..flows.bank_choice import choose_bank
from ..flows.holder import account_holder
from ..flows.inputs import clean_account
from ..flows.provider_error import as_domain_error
from ..ids import new_wallet_entry_id, new_withdrawal_id
from ..mask import mask_account
from ..money import Kobo
from ..paystack.api import PaystackApi, PaystackError, Recipient, RecipientRequest
from .journal import Journal, withdrawn_since
from .withdrawal_block import blocked_sql
from .withdrawal_outcome import WithdrawalOutcomes
from .withdrawal_record import Withdrawal, withdrawal_of
from .withdrawal_refusal import WithdrawalRefusals

WITHDRAWAL_MINUTES = 10


_OPEN = (
    "INSERT INTO wallet_withdrawal (id, owner, amount_kobo, bank_code, bank_name, account_number, "
    "account_name, recipient_code, state, created_at, expires_at) "
    "SELECT ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ? "
    "WHERE EXISTS (SELECT 1 FROM wallet WHERE owner = ? AND frozen = 0) AND ? <= ?"
)
_TAKE = (
    "INSERT INTO wallet_entry (id, owner, kind, sign, amount_kobo, ref, quote_id, created_at) "
    "SELECT ?, w.owner, 'withdraw', -1, w.amount_kobo, w.id, NULL, ? FROM wallet_withdrawal AS w "
    "WHERE w.id = ? AND w.owner = ? AND w.state = 'open' AND w.expires_at > ? "
    "AND w.amount_kobo = ? AND w.account_name = ? AND w.amount_kobo <= ? "
    "AND EXISTS (SELECT 1 FROM wallet AS v WHERE v.owner = w.owner AND v.frozen = 0) "
    f"AND NOT {blocked_sql('w.owner')} "
    "AND (SELECT COALESCE(SUM(e.sign * e.amount_kobo), 0) FROM wallet_entry AS e "
    "WHERE e.owner = w.owner) >= w.amount_kobo "
    f"AND w.amount_kobo + {withdrawn_since('w.owner')} <= ? "
    "ON CONFLICT (owner, kind, ref) DO NOTHING"
)
_MARK_SENT = (
    "UPDATE wallet_withdrawal SET state = 'sent', name_confirmed_at = ?, sending_since = ? "
    "WHERE id = ? AND owner = ? AND state = 'open' "
    "AND EXISTS (SELECT 1 FROM wallet_entry AS e WHERE e.owner = wallet_withdrawal.owner "
    "AND e.kind = 'withdraw' AND e.ref = wallet_withdrawal.id "
    "AND e.amount_kobo = wallet_withdrawal.amount_kobo)"
)


class Withdrawals:
    def __init__(
        self,
        db: Db,
        clock: Clock,
        journal: Journal,
        paystack: PaystackApi,
        secret: str,
        audit: Audit,
    ) -> None:
        self._db = db
        self._clock = clock
        self.journal = journal
        self._paystack = paystack
        self.outcomes = WithdrawalOutcomes(db, clock, paystack, audit)
        self._secret = secret.encode()
        self._audit = audit
        self.refusals = WithdrawalRefusals(db, journal)

    def token(self, withdrawal_id: str) -> str:
        return hmac.new(self._secret, f"withdrawal:{withdrawal_id}".encode(), hashlib.sha256).hexdigest()

    async def get(self, owner: str, withdrawal_id: str) -> Withdrawal | None:
        row = await self._db.row(
            "SELECT * FROM wallet_withdrawal WHERE id = ? AND owner = ?", withdrawal_id, owner
        )
        return withdrawal_of(row) if row else None

    async def start(self, owner: str, amount: Kobo, bank: str, account_number: str) -> Withdrawal:
        """An open withdrawal to the account the bank resolved; nothing is taken until it is approved."""
        await self.refusals.assert_may_withdraw(owner, amount, self._day_start())
        chosen = choose_bank(bank, None)
        account = clean_account(account_number)
        name = await account_holder(self._paystack, account, chosen.code)
        recipient = await self._recipient(name, account, chosen.code)
        withdrawal_id, now = new_withdrawal_id(), self._clock.now()
        cap = self.journal.settings.withdrawal_kobo
        opened = await self._db.execute(
            _OPEN,
            withdrawal_id, owner, amount, chosen.code, chosen.name or recipient.bank_name, account, name,
            recipient.recipient_code, now, now + WITHDRAWAL_MINUTES * 60_000, owner, amount, cap,
        )  # fmt: skip
        if opened != 1:
            raise await self.refusals.why_not_opened(owner)
        self._audit.log(
            "withdrawal.opened", withdrawal=withdrawal_id, amount_kobo=amount, account=mask_account(account)
        )
        found = await self.get(owner, withdrawal_id)
        assert found is not None
        return found

    async def _recipient(self, name: str, account: str, bank_code: str) -> Recipient:
        try:
            return await self._paystack.create_recipient(RecipientRequest(name, account, bank_code))
        except PaystackError as error:
            raise as_domain_error(error, "look up that account") from error

    def _day_start(self) -> int:
        return lagos_day_start(self._clock.now())

    async def approve(
        self, owner: str, withdrawal_id: str, token: str, displayed_amount: Kobo, confirmed_name: str
    ) -> Withdrawal:
        """The person's Withdraw: the money taken and the transfer sent, or the first press's outcome."""
        if not hmac.compare_digest(self.token(withdrawal_id), token):
            self._audit.log("withdrawal.denied", withdrawal=withdrawal_id, why="token")
            raise DomainError("WITHDRAWAL_DENIED", "Only the wallet card can approve a withdrawal.")
        now = self._clock.now()
        moved = await self._take(owner, withdrawal_id, displayed_amount, confirmed_name, now)
        withdrawal = await self.get(owner, withdrawal_id)
        if withdrawal is None:
            raise DomainError("WITHDRAWAL_NOT_FOUND", "There is no such withdrawal. Nothing was taken.")
        if not moved:
            if withdrawal.state != "open":
                return withdrawal
            raise await self.refusals.why_not_taken(
                withdrawal, displayed_amount, confirmed_name, now, lagos_day_start(now)
            )
        self._audit.log("withdrawal.approved", withdrawal=withdrawal.id, amount_kobo=withdrawal.amount_kobo)
        return await self.outcomes.send(withdrawal)

    async def _take(self, owner: str, withdrawal_id: str, displayed: Kobo, name: str, now: int) -> bool:
        """The `withdraw` entry and `open → sent`, in one batch; true when this call moved it to sent."""
        settings = self.journal.settings
        take = (
            new_wallet_entry_id(), now, withdrawal_id, owner, now, displayed, name,
            settings.withdrawal_kobo, lagos_day_start(now), settings.withdrawals_daily_kobo,
        )  # fmt: skip
        results = await self._db.batch([(_TAKE, take), (_MARK_SENT, (now, now, withdrawal_id, owner))])
        return results[1].changes == 1
