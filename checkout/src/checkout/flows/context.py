# SPDX-License-Identifier: AGPL-3.0-or-later
"""Everything a flow needs, passed in so that tests and the Worker wire the same code differently."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from ..audit import Audit
from ..clock import Clock
from ..commerce.checks import AccountChecks
from ..commerce.index.build import IndexParts
from ..commerce.registry import Providers
from ..ledger import Ledger
from ..memory.store import MemoryStore
from ..modes import Modes
from ..paystack.api import PaystackApi
from ..refunds.owed import RefundRequests
from ..vtpass.api import VtpassApi
from ..wallet.spending import WalletSpending


@dataclass(frozen=True)
class Context:
    ledger: Ledger
    paystack: PaystackApi
    modes: Modes
    audit: Audit
    clock: Clock
    payer_email: str
    checkout_window_seconds: int
    vtpass: VtpassApi | None = None
    food_step_seconds: int = 15
    card_csp_extra: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    inline_checkout: bool = False
    """The card may pay in Paystack's popup: real Paystack test mode, and the switch is on."""
    memory: MemoryStore | None = None
    """Where a saved recipient is read from, when a transfer names one."""
    wallet: WalletSpending | None = None
    """Pays an approved quote from the owner's wallet instead of a checkout (docs/wallet.md)."""
    refunds: RefundRequests | None = None
    """Asks for the Paystack refund of a quote paid at the checkout that ends owing one (refunds/)."""
    providers: Providers | None = None
    """The merchants a `merchants` quote is made for and fulfilled by (commerce/)."""
    checks: AccountChecks | None = None
    """The account checks a quote for a merchant that checks accounts carries (commerce/checks.py)."""
    index: IndexParts | None = None
    """Paystack Index: the connect card's accounts and, where it is simulated, the simulator (commerce/index/)."""
    free_text_merchants: bool = True
    """`create_payment_quote` may name any merchant in words (`FREE_TEXT_MERCHANTS`, config.py)."""


@dataclass(frozen=True)
class QuoteIssued:
    """A quote just made: the card's view of it, and the token only the card is given."""

    quote: dict[str, Any]
    approval_token: str
    replayed: bool
    told: str = ""
    """What the model is told beside the quote for this request alone (flows/wallet_leg.py)."""
