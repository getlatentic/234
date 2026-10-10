# SPDX-License-Identifier: AGPL-3.0-or-later
"""The spend limits checked before a quote is made, and the reason a refused approval gives.

The approval's own UPDATE holds the same limits in one statement (approval.py); these checks refuse early,
so no provider is called for an amount that could never be approved.
"""

from ..amount_floor import assert_above_floor
from ..clock import lagos_day_start
from ..errors import DomainError
from ..money import Kobo, format_naira
from ..owner import current_group
from .records import SPENDING_SQL, Budget
from .store import QuoteStore


class SpendLimits(QuoteStore):
    async def _group_spent(self, group: str) -> Kobo:
        row = await self._db.row(
            f"SELECT COALESCE(SUM(amount_kobo), 0) AS spent FROM quotes "
            f"WHERE payer_group = ? AND approved_at >= ? AND state IN ({SPENDING_SQL})",
            group,
            lagos_day_start(self._clock.now()),
        )
        return int(row["spent"])

    async def _assert_within_group(self, amount: Kobo, group: str) -> None:
        if group and await self._group_spent(group) + amount > self.limits.group_daily_kobo:
            raise DomainError(
                "LIMIT_GROUP_DAILY",
                f"{format_naira(amount)} would take what the people of this agent approved today above "
                f"{format_naira(self.limits.group_daily_kobo)}, "
                "the most one agent's people can spend in a day.",
            )

    async def budget(self) -> Budget:
        row = await self._db.row(
            f"SELECT COALESCE(SUM(amount_kobo), 0) AS spent FROM quotes "
            f"WHERE owner = ? AND approved_at >= ? AND state IN ({SPENDING_SQL})",
            self.owner(),
            lagos_day_start(self._clock.now()),
        )
        return Budget(self.limits.per_payment_kobo, self.limits.daily_kobo, int(row["spent"]))

    def _assert_within_per_payment(self, amount: Kobo) -> None:
        if amount > self.limits.per_payment_kobo:
            raise DomainError(
                "LIMIT_PER_PAYMENT",
                f"{format_naira(amount)} is above the per-payment limit of "
                f"{format_naira(self.limits.per_payment_kobo)}.",
            )

    def _assert_within_daily(self, amount: Kobo, spent: Kobo) -> None:
        if spent + amount > self.limits.daily_kobo:
            left = max(self.limits.daily_kobo - spent, 0)
            raise DomainError(
                "LIMIT_DAILY",
                f"{format_naira(amount)} would take today's approved total above the daily limit "
                f"of {format_naira(self.limits.daily_kobo)} ({format_naira(left)} left today).",
            )

    async def assert_quotable(self, amount: Kobo) -> None:
        """Refuses an amount the floor or the limits do not allow, so no provider is called for it."""
        assert_above_floor(amount)
        self._assert_within_per_payment(amount)
        self._assert_within_daily(amount, (await self.budget()).spent_today_kobo)
        await self._assert_within_group(amount, current_group())
