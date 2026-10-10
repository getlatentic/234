# SPDX-License-Identifier: AGPL-3.0-or-later
"""Starting a top-up (docs/wallet.md, "Funding"): a `wallet_topup` row, then a Bachs checkout for exactly its
amount with the top-up's id as the reference (migrations/0012_wallet_topup.sql).

The row is one INSERT ... SELECT whose WHERE holds the rules, as journal.py's movements do: the owner's wallet
exists (a signed-in account; a visitor has none) and is not frozen, and the balance plus the amount stays
within the cap. The cap is held again when the money arrives (topup_credit.py): two top-ups started side by
side can each fit now and not both fit later.

No Bachs call happens inside a statement. A checkout that could not be made leaves the top-up expired: its URL
was never handed out, so nobody can pay it."""

import hashlib
from dataclasses import dataclass
from typing import Any

from ..bachs.api import BachsApi, BachsError, CheckoutRequest
from ..bachs.events import OWNER_TAG
from ..clock import Clock
from ..db import Db
from ..errors import DomainError
from ..ids import new_topup_id
from ..money import Kobo, format_naira
from .journal import BALANCE_SQL, Journal

TOPUP_MINUTES = 60


@dataclass(frozen=True)
class TopUp:
    id: str
    owner: str
    amount_kobo: Kobo
    state: str
    provider_ref: str | None
    checkout_url: str | None
    created_at: int
    expires_at: int
    paid_at: int | None


@dataclass(frozen=True)
class CheckoutTerms:
    """What every checkout carries besides the amount: who Bachs is told pays, and where the payer returns."""

    customer_email: str | None = None
    success_url: str | None = None


def topup_of(row: dict[str, Any]) -> TopUp:
    return TopUp(
        row["id"], row["owner"], row["amount_kobo"], row["state"], row["provider_ref"], row["checkout_url"],
        row["created_at"], row["expires_at"], row["paid_at"],
    )  # fmt: skip


def owner_tag(owner: str) -> str:
    """The owner as Bachs sees it in the checkout's metadata: a digest, so the owner key never leaves 234."""
    return hashlib.sha256(f"234-wallet-owner:{owner}".encode()).hexdigest()[:32]


_OPEN = (
    "INSERT INTO wallet_topup (id, owner, amount_kobo, state, created_at, expires_at) "
    "SELECT ?, ?, ?, 'open', ?, ? "
    "WHERE EXISTS (SELECT 1 FROM wallet WHERE owner = ? AND frozen = 0) "
    f"AND {BALANCE_SQL} + ? <= ?"
)


class TopUps:
    def __init__(self, db: Db, clock: Clock, journal: Journal, bachs: BachsApi, terms: CheckoutTerms) -> None:
        self._db = db
        self._clock = clock
        self.journal = journal
        self._bachs = bachs
        self._terms = terms

    async def start(self, owner: str, amount: Kobo) -> TopUp:
        """A top-up for the owner's wallet, with the Bachs checkout to pay it on."""
        if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
            raise DomainError("INVALID_INPUT", "A top-up is a positive whole number of kobo.")
        topup_id, now = new_topup_id(), self._clock.now()
        cap = self.journal.settings.balance_cap_kobo
        opened = await self._db.execute(
            _OPEN, topup_id, owner, amount, now, now + TOPUP_MINUTES * 60_000, owner, owner, amount, cap
        )
        if opened != 1:
            raise await self._why_not(owner, amount)
        try:
            checkout = await self._bachs.create_checkout(self._request(topup_id, owner, amount))
        except BachsError as error:
            await self._db.execute(
                "UPDATE wallet_topup SET state = 'expired' WHERE id = ? AND state = 'open'", topup_id
            )
            raise DomainError(
                "TOPUP_UNAVAILABLE", "Bachs could not start the payment. Nothing was taken."
            ) from error
        await self._db.execute(
            "UPDATE wallet_topup SET provider_ref = ?, checkout_url = ?, expires_at = ? "
            "WHERE id = ? AND state = 'open' AND provider_ref IS NULL",
            checkout.checkout_id,
            checkout.checkout_url,
            checkout.expires_at,
            topup_id,
        )
        found = await self.get(topup_id)
        assert found is not None
        return found

    def _request(self, topup_id: str, owner: str, amount: Kobo) -> CheckoutRequest:
        return CheckoutRequest(
            reference=topup_id,
            amount_kobo=amount,
            expires_in_minutes=TOPUP_MINUTES,
            metadata={"wallet_topup": topup_id, OWNER_TAG: owner_tag(owner)},
            customer_email=self._terms.customer_email,
            success_url=self._terms.success_url,
        )

    async def _why_not(self, owner: str, amount: Kobo) -> DomainError:
        row = await self._db.row("SELECT frozen FROM wallet WHERE owner = ?", owner)
        if row is None:
            return DomainError("WALLET_NONE", "A wallet is for signed-in accounts. Sign in to add money.")
        if row["frozen"]:
            return DomainError("WALLET_FROZEN", "This wallet is frozen, so it cannot take money.")
        room = max(self.journal.settings.balance_cap_kobo - await self.journal.balance(owner), 0)
        return DomainError(
            "WALLET_CAP",
            f"The wallet can take at most {format_naira(room)} more, less than {format_naira(amount)}.",
        )

    async def get(self, topup_id: str) -> TopUp | None:
        row = await self._db.row("SELECT * FROM wallet_topup WHERE id = ?", topup_id)
        return topup_of(row) if row else None

    async def expire_due(self) -> int:
        """Open top-ups past their checkout's expiry, now expired; how many."""
        return await self._db.execute(
            "UPDATE wallet_topup SET state = 'expired' WHERE state = 'open' AND expires_at <= ?",
            self._clock.now(),
        )
