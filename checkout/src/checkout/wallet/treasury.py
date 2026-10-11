# SPDX-License-Identifier: AGPL-3.0-or-later
"""What 234 holds where wallet money lives (docs/wallet.md, "Where the money is, and the float"): its NGN at
Bachs, where top-ups arrive; at Paystack, which pays withdrawals; and at VTpass, which pays airtime and data.
234 tops up Paystack and VTpass itself, so together they are what stands against what it owes.

A provider that cannot be read is None, never zero, and is audited: an unknown balance says nothing about a
shortfall."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from ..audit import Audit
from ..bachs.api import BachsApi, BachsError
from ..money import Kobo
from ..paystack.api import PaystackApi, PaystackError
from ..vtpass.api import VtpassApi

Reading = Callable[[], Awaitable[Kobo]]


@dataclass(frozen=True)
class Held:
    bachs_kobo: Kobo | None
    paystack_kobo: Kobo | None
    vtpass_kobo: Kobo | None

    @property
    def total_kobo(self) -> Kobo | None:
        parts = (self.bachs_kobo, self.paystack_kobo, self.vtpass_kobo)
        return None if any(part is None for part in parts) else sum(p for p in parts if p is not None)


class Treasury:
    def __init__(
        self, bachs: BachsApi, paystack: PaystackApi, vtpass: VtpassApi | None, audit: Audit
    ) -> None:
        self._readings: dict[str, Reading] = {
            "bachs": bachs.ngn_balance,
            "paystack": paystack.ngn_balance,
            "vtpass": self._vtpass_reading(vtpass),
        }
        self._audit = audit

    @staticmethod
    def _vtpass_reading(vtpass: VtpassApi | None) -> Reading:
        async def read() -> Kobo:
            check = await vtpass.check_access() if vtpass else None
            if check is None or not check.ok or check.balance_kobo is None:
                raise LookupError(check.reason if check else "VTpass is not configured.")
            return check.balance_kobo

        return read

    async def held(self) -> Held:
        read = {name: await self._read(name, reading) for name, reading in self._readings.items()}
        return Held(read["bachs"], read["paystack"], read["vtpass"])

    async def _read(self, name: str, reading: Reading) -> Kobo | None:
        try:
            return await reading()
        except (BachsError, PaystackError, LookupError) as error:
            self._audit.log("wallet.reconcile.unread", provider=name, why=str(error)[:120])
            return None
