# SPDX-License-Identifier: AGPL-3.0-or-later
"""The `airtime` connector: airtime or data for a Nigerian mobile number. The person pays through
Paystack, then VTpass delivers."""

from typing import Annotated

from pydantic import Field

from ..flows.airtime import AirtimeFlow
from ..flows.context import Context, QuoteIssued
from ..mcp.registry import Connector, ToolResult
from ..money import format_naira
from ..network import NETWORK_LABEL, Network
from .kit import CardConnector, CardReader, IdempotencyKey, Strict, plain_result

NAME = "airtime"

NetworkField = Annotated[Network, Field(description="The mobile network.")]
PhoneField = Annotated[
    str,
    Field(
        min_length=10,
        max_length=16,
        description="The Nigerian mobile number to top up, such as 08031234567 or +2348031234567.",
    ),
]


class CreateAirtimeQuote(Strict):
    network: NetworkField
    phone: PhoneField
    amount_kobo: Annotated[
        int,
        Field(
            gt=0,
            description="The amount in kobo: 100 kobo is 1 naira, so 500 naira is 50000. "
            "Whole naira, at least 50.",
        ),
    ]
    amount_as_user_said: Annotated[
        str,
        Field(
            min_length=1,
            max_length=80,
            description='The amount exactly as the person said or wrote it, for example "500" or '
            '"two hundred naira". It is checked against amount_kobo.',
        ),
    ]
    idempotency_key: IdempotencyKey


class CreateDataQuote(Strict):
    network: NetworkField
    phone: PhoneField
    plan_code: Annotated[
        str, Field(min_length=1, max_length=60, description="A plan code from list_data_plans.")
    ]
    idempotency_key: IdempotencyKey


class ListDataPlans(Strict):
    network: NetworkField


def build_connector(ctx: Context, card_html: CardReader) -> Connector:
    flow = AirtimeFlow(ctx)
    kit = CardConnector(NAME, "Airtime and data", ctx, flow, card_html)

    async def create_airtime(args: CreateAirtimeQuote) -> QuoteIssued:
        return await flow.create_airtime_quote(**args.model_dump())

    async def create_data(args: CreateDataQuote) -> QuoteIssued:
        return await flow.create_data_quote(**args.model_dump())

    async def list_plans(args: ListDataPlans) -> ToolResult:
        plans = await flow.list_data_plans(args.network)
        lines = [f"{p.code}: {p.name}, {format_naira(p.amount_kobo)}" for p in plans]
        return plain_result(
            f"{NETWORK_LABEL[args.network]} data plans:\n" + "\n".join(lines),
            {
                "plans": [
                    {
                        "code": p.code,
                        "name": p.name,
                        "amountKobo": p.amount_kobo,
                        "price": format_naira(p.amount_kobo),
                    }
                    for p in plans
                ]
            },
        )

    tools = (
        kit.quote_tool(
            "create_airtime_quote",
            "Create airtime quote",
            "Creates a server-side quote for airtime and shows the person a card with the network, the "
            "number and the amount to read back and confirm. Nothing is bought until the person confirms, "
            "presses Approve and pays on Paystack's checkout.",
            CreateAirtimeQuote,
            create_airtime,
        ),
        kit.quote_tool(
            "create_data_quote",
            "Create data quote",
            "Creates a server-side quote for a data plan and shows the person a card to read back and "
            "confirm. The price is the plan's own. Use a plan_code from list_data_plans.",
            CreateDataQuote,
            create_data,
        ),
        kit.plain_tool(
            "list_data_plans",
            "List data plans",
            "Lists the data plans a network sells, with their codes and prices.",
            ListDataPlans,
            list_plans,
        ),
    )
    return kit.build(
        "Buy airtime or data for a Nigerian mobile number: the person pays through Paystack, then VTpass "
        "delivers",
        tools,
        (
            "Read the number and the amount back to the person before they approve; the card asks them to "
            "confirm both.",
            "For data, call list_data_plans first and quote with one of its plan codes. The price comes "
            "from the plan.",
        ),
    )
