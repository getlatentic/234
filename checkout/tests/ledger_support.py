# SPDX-License-Identifier: AGPL-3.0-or-later
"""A quote request for the ledger tests."""

from checkout.ledger import NewQuote, request_hash


def new_quote(amount: int = 250_000, key: str = "key-00000001", description: str = "Lunch") -> NewQuote:
    return NewQuote(
        connector="paystack-pay",
        kind="payment",
        amount_kobo=amount,
        description=description,
        merchant="Demo Kitchen",
        merchant_ref=None,
        details={"kind": "payment"},
        idempotency_key=key,
        request_hash=request_hash(
            amount_kobo=amount, description=description, merchant="Demo Kitchen", merchant_ref=None
        ),
    )
