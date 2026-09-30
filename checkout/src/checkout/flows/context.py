# SPDX-License-Identifier: AGPL-3.0-or-later
"""Everything a flow needs, passed in so that tests and the Worker wire the same code differently."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from ..audit import Audit
from ..clock import Clock
from ..ledger import Ledger
from ..modes import Modes
from ..paystack.api import PaystackApi
from ..vtpass.api import VtpassApi


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


@dataclass(frozen=True)
class QuoteIssued:
    """A quote just made: the card's view of it, and the token only the card is given."""

    quote: dict[str, Any]
    approval_token: str
    replayed: bool
