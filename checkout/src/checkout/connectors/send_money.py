# SPDX-License-Identifier: AGPL-3.0-or-later
"""The `send-money` connector: send money to a Nigerian bank account with Paystack Transfers."""

from typing import Annotated

from pydantic import ConfigDict, Field

from ..flows.context import Context, QuoteIssued
from ..flows.transfer import TransferFlow
from ..mcp.registry import Connector
from .kit import CardConnector, CardReader, IdempotencyKey, Strict

NAME = "send-money"


class CreateTransferQuote(Strict):
    model_config = ConfigDict(json_schema_extra={"x-model-required": ["bank"]})

    account_number: Annotated[
        str, Field(min_length=10, max_length=14, description="The recipient's 10 digit account number.")
    ]
    bank: Annotated[
        str | None,
        Field(
            min_length=2,
            max_length=60,
            description='The bank exactly as the person named it, for example "GTB", "Guaranty Trust", '
            '"Access" or "OPay". The server finds the bank on Paystack\'s list and refuses a name it cannot '
            "match to one bank; never turn it into a code. If the person named no bank, ask which.",
        ),
    ] = None
    bank_code: Annotated[
        str | None,
        Field(
            min_length=3,
            max_length=6,
            description="The bank's Paystack code, for example 057 for Zenith Bank. An addition to the "
            "TypeScript contract, which takes only this: a client that holds the code sends it instead of "
            "`bank`, or with it, and the two must name the same bank.",
            json_schema_extra={"x-model-hidden": True},
        ),
    ] = None
    amount_kobo: Annotated[int, Field(gt=0, description="The amount in kobo: 100 kobo is 1 naira.")]
    amount_as_user_said: Annotated[
        str,
        Field(
            min_length=1,
            max_length=80,
            description='The amount exactly as the person said or wrote it, for example "25k". '
            "It is checked against amount_kobo.",
        ),
    ]
    narration: Annotated[
        str | None, Field(max_length=100, description="A short note that appears with the transfer.")
    ] = None
    idempotency_key: IdempotencyKey


def build_connector(ctx: Context, card_html: CardReader) -> Connector:
    flow = TransferFlow(ctx)
    kit = CardConnector(NAME, "Send money", ctx, flow, card_html)

    async def create(args: CreateTransferQuote) -> QuoteIssued:
        return await flow.create_quote(**args.model_dump())

    quote = kit.quote_tool(
        "create_transfer_quote",
        "Create transfer quote",
        "Looks up the bank account, then creates a server-side quote for sending money to it and shows "
        "the person an approval card with the recipient's verified name, the bank, the amount and their "
        "spending limits. Nothing is sent until the person presses Approve.",
        CreateTransferQuote,
        create,
    )
    return kit.build(
        "Send money to a Nigerian bank account with Paystack Transfers",
        (quote,),
        (
            "Test mode only accepts Paystack's test account: 0000000000 at Zenith Bank. "
            "The simulator accepts any 10 digit account.",
            "If the card reports that transfers are not enabled on this account, say so plainly and do "
            "not retry; the owner can switch this connector to simulated mode.",
            "The recipient's name shown on the card comes from the bank's own account lookup, not from you.",
        ),
        submit_otp=flow.submit_otp,
    )
