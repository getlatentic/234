# SPDX-License-Identifier: AGPL-3.0-or-later
"""The `paystack-pay` connector: pay a merchant through Paystack's hosted checkout."""

from typing import Annotated

from pydantic import Field

from ..flows.context import Context, QuoteIssued
from ..flows.payment import PaymentFlow
from ..mcp.registry import Connector
from .kit import CardConnector, CardReader, IdempotencyKey, Strict

NAME = "paystack-pay"


class CreatePaymentQuote(Strict):
    amount_kobo: Annotated[
        int,
        Field(gt=0, description="The amount in kobo: 100 kobo is 1 naira, so 5,000 naira is 500000."),
    ]
    amount_as_user_said: Annotated[
        str,
        Field(
            min_length=1,
            max_length=80,
            description='The amount exactly as the person said or wrote it, for example "5k" or '
            '"two thousand naira". It is checked against amount_kobo.',
        ),
    ]
    description: Annotated[
        str,
        Field(min_length=1, max_length=140, description="What the payment is for, in plain words."),
    ]
    merchant: Annotated[str, Field(min_length=1, max_length=60, description="The merchant's display name.")]
    merchant_ref: Annotated[
        str | None,
        Field(max_length=64, description="The merchant's own reference for this order, if there is one."),
    ] = None
    idempotency_key: IdempotencyKey


def build_connector(ctx: Context, card_html: CardReader, alt_cards: dict[str, CardReader]) -> Connector:
    flow = PaymentFlow(ctx)
    kit = CardConnector(NAME, "Paystack Pay", ctx, flow, card_html, alt_cards)

    async def create(args: CreatePaymentQuote) -> QuoteIssued:
        return await flow.create_quote(**args.model_dump())

    quote = kit.quote_tool(
        "create_payment_quote",
        "Create payment quote",
        "Creates a server-side quote for paying a merchant, and shows the person an approval "
        "card with the amount, what it is for, and their spending limits. The amount cannot "
        "be changed after this call. Nothing is charged until the person presses Approve on "
        "the card and completes Paystack's checkout.",
        CreatePaymentQuote,
        create,
    )
    return kit.build("Pay a merchant through Paystack's hosted checkout", (quote,))
