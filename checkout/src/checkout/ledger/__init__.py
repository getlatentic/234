# SPDX-License-Identifier: AGPL-3.0-or-later
"""Quotes, the spend they reserve, and the rules that keep both honest.

D1 has no interactive transactions, so no rule here reads and then writes. Each is a constraint in the
schema or one conditional UPDATE whose WHERE clause holds the rule, and the number of rows it changed says
whether this caller won. Each module states the rules its statements hold: the owner of every read
(store.py), idempotency (making.py), one approval and the daily limits (approval.py), and progress merged
in SQL (progress.py).
"""

from .approval import Approvals
from .progress import ProgressWrites
from .records import (
    ENDED_STATES,
    SPENDING_STATES,
    Budget,
    CheckoutFacts,
    ClaimTerms,
    Limits,
    NewQuote,
    Quote,
    quote_of,
    request_hash,
)


class Ledger(Approvals, ProgressWrites):
    """Every operation on quotes, as the owner of the call."""


__all__ = [
    "ENDED_STATES",
    "SPENDING_STATES",
    "Budget",
    "CheckoutFacts",
    "ClaimTerms",
    "Ledger",
    "Limits",
    "NewQuote",
    "Quote",
    "quote_of",
    "request_hash",
]
