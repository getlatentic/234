# SPDX-License-Identifier: AGPL-3.0-or-later
"""Paying a quote from the wallet (docs/wallet.md, "hold, claim, release"), keyed by the quote id.

1. Hold: a `spend` entry, guarded by the balance (journal.py).
2. Claim: the quote's one approval (Ledger.claim_approval), which in the same UPDATE marks the quote as paid
   from the wallet and requires a hold of its amount that was never released.
3. Release: a lost claim gives the hold back.

Release and the wallet's claim exclude each other in SQL, not in Python: the claim requires that no release
exists, and a release is written only while no quote of that id is marked as paid from the wallet. Whichever
statement runs first wins, so a retried approval, a claim whose answer was lost, or a race with a checkout
approval can neither keep a quote paid without its hold nor give back money a delivered quote spent.

A provider that fails after a wallet approval pays back with `refund`, written only for a quote in
`refund_due` that the wallet paid, and for exactly what its hold took.
"""

from typing import Any

from ..clock import Clock
from ..db import Db
from ..errors import DomainError
from ..ids import new_wallet_entry_id
from ..ledger import ClaimTerms, Ledger, Quote
from ..money import format_naira
from .journal import Entry, Journal

WALLET_PAID: dict[str, Any] = {"funding": "wallet", "paymentStatus": "success"}

HOLD_LIVE = (
    "EXISTS (SELECT 1 FROM wallet_entry AS h WHERE h.owner = quotes.owner AND h.kind = 'spend' "
    "AND h.ref = quotes.id AND h.amount_kobo = quotes.amount_kobo) "
    "AND NOT EXISTS (SELECT 1 FROM wallet_entry AS r WHERE r.owner = quotes.owner AND r.kind = 'release' "
    "AND r.ref = quotes.id)"
)
_GIVE_BACK = (
    "INSERT INTO wallet_entry (id, owner, kind, sign, amount_kobo, ref, quote_id, created_at) "
    "SELECT ?, h.owner, ?, 1, h.amount_kobo, h.ref, h.quote_id, ? FROM wallet_entry AS h "
    "WHERE h.owner = ? AND h.kind = 'spend' AND h.ref = ? AND "
)
_NOT_PAID_FROM_WALLET = (
    "NOT EXISTS (SELECT 1 FROM quotes AS q WHERE q.id = h.ref AND q.owner = h.owner "
    "AND json_extract(q.progress, '$.funding') = 'wallet')"
)
_PAID_AND_REFUND_DUE = (
    "EXISTS (SELECT 1 FROM quotes AS q WHERE q.id = h.ref AND q.owner = h.owner AND q.state = 'refund_due' "
    "AND json_extract(q.progress, '$.funding') = 'wallet')"
)
_ON_CONFLICT = " ON CONFLICT (owner, kind, ref) DO NOTHING"


def paid_from_wallet(quote: Quote) -> bool:
    return quote.progress.get("funding") == "wallet"


class WalletSpending:
    def __init__(self, journal: Journal, db: Db, clock: Clock) -> None:
        self.journal = journal
        self._db = db
        self._clock = clock

    async def hold(self, owner: str, quote: Quote) -> Entry:
        """Takes the quote's amount from the wallet, or finds the hold an earlier call took."""
        held = await self.journal.debit(owner, "spend", quote.amount_kobo, quote.id, quote.id)
        if held is None:
            raise await self._why_not_held(owner, quote)
        if await self.journal.entry(owner, "release", quote.id) is not None:
            raise DomainError(
                "WALLET_RELEASED",
                "The wallet already gave this quote's money back. Approve it with the checkout instead.",
            )
        return held

    async def _why_not_held(self, owner: str, quote: Quote) -> DomainError:
        if await self.journal.is_frozen(owner):
            return DomainError("WALLET_FROZEN", "This wallet is frozen, so it cannot pay. Nothing was taken.")
        balance = await self.journal.balance(owner)
        return DomainError(
            "WALLET_SHORT",
            f"The wallet holds {format_naira(balance)}, less than this quote's "
            f"{format_naira(quote.amount_kobo)}. Nothing was taken.",
        )

    async def pay(self, ledger: Ledger, quote: Quote) -> tuple[Quote, bool]:
        """Hold, claim, release: the quote's approval, paid from the owner's wallet. A claim that did not
        land for this wallet, however it failed, gives the hold back."""
        owner = ledger.owner()
        await self.hold(owner, quote)
        try:
            claimed_quote, claimed = await ledger.claim_approval(
                quote.id, quote.connector, ClaimTerms(WALLET_PAID, HOLD_LIVE)
            )
        except BaseException:
            await self.release(owner, quote.id)
            raise
        if not claimed:
            await self.release(owner, quote.id)
        return claimed_quote, claimed

    async def release(self, owner: str, quote_id: str) -> bool:
        """Gives back the hold on a quote the wallet did not pay; true when a release is now recorded."""
        return await self._give_back(owner, quote_id, "release", _NOT_PAID_FROM_WALLET)

    async def refund(self, owner: str, quote_id: str) -> bool:
        """Pays back a wallet-paid quote its provider failed; true when the refund is now recorded."""
        return await self._give_back(owner, quote_id, "refund", _PAID_AND_REFUND_DUE)

    async def _give_back(self, owner: str, quote_id: str, kind: str, condition: str) -> bool:
        await self._db.execute(
            f"{_GIVE_BACK}{condition}{_ON_CONFLICT}",
            new_wallet_entry_id(),
            kind,
            self._clock.now(),
            owner,
            quote_id,
        )
        return await self.journal.entry(owner, kind, quote_id) is not None
