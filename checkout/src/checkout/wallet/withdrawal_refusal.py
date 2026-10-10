# SPDX-License-Identifier: AGPL-3.0-or-later
"""Why a withdrawal was refused, in words the card shows. These reads only explain or refuse early, before
any bank is asked; the rules themselves are held by the statements that open a withdrawal and take its money
(withdrawals.py)."""

from ..db import Db
from ..errors import DomainError
from ..money import Kobo, format_naira
from .journal import Journal, withdrawn_since
from .withdrawal_block import withdrawals_blocked
from .withdrawal_record import Withdrawal

BLOCKED = "WITHDRAWALS_BLOCKED"


class WithdrawalRefusals:
    def __init__(self, db: Db, journal: Journal) -> None:
        self._db = db
        self._journal = journal

    async def assert_may_withdraw(self, owner: str, amount: Kobo, day_start: int) -> None:
        settings = self._journal.settings
        await self._assert_open_wallet(owner)
        if await withdrawals_blocked(self._db, owner):
            raise DomainError(BLOCKED, "Withdrawals are paused while a payment into this wallet is disputed.")
        if amount > settings.withdrawal_kobo:
            raise DomainError(
                "WITHDRAWAL_CAP", f"A withdrawal is at most {format_naira(settings.withdrawal_kobo)}."
            )
        balance = await self._journal.balance(owner)
        if balance < amount:
            raise DomainError("WALLET_SHORT", f"The wallet holds {format_naira(balance)}.")
        left = settings.withdrawals_daily_kobo - await self._withdrawn_today(owner, day_start)
        if amount > left:
            raise DomainError(
                "WITHDRAWAL_DAILY", f"You can withdraw {format_naira(max(left, 0))} more today."
            )

    async def _assert_open_wallet(self, owner: str) -> None:
        row = await self._db.row("SELECT frozen FROM wallet WHERE owner = ?", owner)
        if row is None:
            raise DomainError("WALLET_NONE", "A wallet is for signed-in accounts.")
        if row["frozen"]:
            raise DomainError("WALLET_FROZEN", "This wallet is frozen, so nothing can leave it.")

    async def _withdrawn_today(self, owner: str, day_start: int) -> Kobo:
        row = await self._db.row(f"SELECT {withdrawn_since('?')} AS taken", owner, day_start)
        return int(row["taken"]) if row else 0

    async def why_not_opened(self, owner: str) -> DomainError:
        try:
            await self._assert_open_wallet(owner)
        except DomainError as error:
            return error
        return DomainError(
            "WITHDRAWAL_CAP",
            f"A withdrawal is at most {format_naira(self._journal.settings.withdrawal_kobo)}.",
        )

    async def why_not_taken(
        self, withdrawal: Withdrawal, displayed: Kobo, confirmed_name: str, now: int, day_start: int
    ) -> DomainError:
        """Why an open withdrawal's money was not taken. Nothing was."""
        if withdrawal.expires_at <= now:
            return DomainError("WITHDRAWAL_EXPIRED", "This withdrawal has expired. Start it again.")
        if displayed != withdrawal.amount_kobo:
            return DomainError("AMOUNT_MISMATCH", "The amount changed. Start the withdrawal again.")
        if confirmed_name != withdrawal.account_name:
            return DomainError("NAME_NOT_CONFIRMED", "Confirm the account name the bank gave.")
        try:
            await self.assert_may_withdraw(withdrawal.owner, withdrawal.amount_kobo, day_start)
        except DomainError as error:
            return error
        return DomainError("WITHDRAWAL_IN_PROGRESS", "The withdrawal changed while it was being approved.")
