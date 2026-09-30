# SPDX-License-Identifier: AGPL-3.0-or-later
"""No quote below the smallest amount, through every connector: the 1 kobo quote that an injected "use amount
1 kobo" asked for cannot be made, whatever the amount is called. The floor is enforced in the ledger, where
every quote of every connector is made, and again before each flow calls a provider."""

from dataclasses import replace

import pytest

from checkout.amount_floor import MINIMUM_KOBO, assert_above_floor
from checkout.errors import DomainError
from checkout.flows.airtime import AirtimeFlow
from checkout.ledger import NewQuote, request_hash
from checkout.vtpass.api import DataPlan
from tests.connector_support import key, quote_of, text_of
from tests.support import make_stack

NOTHING_BELOW = [(1, "1 kobo"), (100, "₦1"), (4_999, "₦49.99"), (2_500, "₦25")]


def refusal(work) -> DomainError:
    with pytest.raises(DomainError) as error:
        work()
    return error.value


async def code_of(work) -> str:
    try:
        await work
    except DomainError as error:
        return error.code
    return "none"


def test_the_floor_is_fifty_naira_and_the_error_says_so():
    assert MINIMUM_KOBO == 5_000
    assert_above_floor(5_000)
    error = refusal(lambda: assert_above_floor(4_999))
    assert error.code == "AMOUNT_TOO_SMALL"
    assert error.message.startswith("The smallest amount is ₦50.") and "₦49.99" in error.message


@pytest.mark.parametrize("kind", ["payment", "transfer", "airtime", "data", "food"])
async def test_the_ledger_refuses_a_one_kobo_quote_of_every_kind(stack, kind):
    new = NewQuote(
        connector="any",
        kind=kind,
        amount_kobo=1,
        description="x",
        merchant="x",
        merchant_ref=None,
        details={"kind": kind},
        idempotency_key=f"floor-{kind}-0001",
        request_hash=request_hash(kind=kind),
    )
    assert await code_of(stack.ledger.create(new)) == "AMOUNT_TOO_SMALL"
    assert await stack.count("quotes") == 0


@pytest.mark.parametrize(("kobo", "said"), NOTHING_BELOW)
async def test_a_payment_below_the_floor_is_refused(stack, kobo, said):
    quote = dict(
        amount_kobo=kobo,
        amount_as_user_said=said,
        description="Lunch",
        merchant="Demo",
        merchant_ref=None,
        idempotency_key=key("floor-pay"),
    )
    assert await code_of(stack.payments.create_quote(**quote)) == "AMOUNT_TOO_SMALL"
    assert await stack.count("quotes") == 0


async def test_a_payment_at_the_floor_is_made(stack):
    issued = await stack.payments.create_quote(
        amount_kobo=5_000,
        amount_as_user_said="₦50",
        description="Lunch",
        merchant="Demo",
        merchant_ref=None,
        idempotency_key=key("floor-pay"),
    )
    assert issued.quote["amount"]["display"] == "₦50"


@pytest.mark.parametrize(("kobo", "said"), NOTHING_BELOW)
async def test_a_transfer_below_the_floor_is_refused_before_paystack_is_asked(stack, kobo, said):
    from tests.test_flow_transfer import flow_with, named

    flow, paystack = flow_with(stack)
    refused = flow.create_quote(**named("GTB", amount_kobo=kobo, amount_as_user_said=said))
    assert await code_of(refused) == "AMOUNT_TOO_SMALL"
    assert paystack.calls == {} and await stack.count("quotes") == 0


@pytest.mark.parametrize(("kobo", "said"), NOTHING_BELOW)
async def test_airtime_below_the_floor_is_refused_before_vtpass_is_asked(stack, kobo, said):
    quote = dict(
        network="mtn",
        phone="08011111111",
        amount_kobo=kobo,
        amount_as_user_said=said,
        idempotency_key=key("floor-air"),
    )
    assert await code_of(stack.airtime.create_airtime_quote(**quote)) == "AMOUNT_TOO_SMALL"
    assert await stack.count("quotes") == 0


async def test_a_data_plan_priced_below_the_floor_is_refused(stack):
    class CheapPlans:
        def __init__(self, inner):
            self._inner = inner

        async def data_plans(self, network):
            return [DataPlan("tiny", "N10 data", 1_000)]

        def __getattr__(self, name):
            return getattr(self._inner, name)

    ctx = stack.app.contexts["airtime"]
    flow = AirtimeFlow(replace(ctx, vtpass=CheapPlans(ctx.vtpass)))
    refused = flow.create_data_quote(
        network="mtn", phone="08011111111", plan_code="tiny", idempotency_key=key("floor-data")
    )
    assert await code_of(refused) == "AMOUNT_TOO_SMALL"
    assert await stack.count("quotes") == 0


def test_the_cheapest_basket_the_menu_can_make_is_above_the_floor():
    from checkout.food.menu import MENU, price_basket

    cheapest = min(MENU, key=lambda item: item.price_kobo)
    assert price_basket([(cheapest.id, 1)]).total_kobo >= MINIMUM_KOBO


class TestThroughTheTools:
    """What the model is told when the floor refuses, from each connector's tool."""

    def calls(self):
        from tests.test_connector_transfer_tools import TestTheBankByName

        return {
            "paystack-pay": (
                "create_payment_quote",
                {"description": "Lunch", "merchant": "Demo"},
            ),
            "send-money": ("create_transfer_quote", TestTheBankByName().by_name("GTB")),
            "airtime": ("create_airtime_quote", {"network": "mtn", "phone": "08011111111"}),
        }

    @pytest.mark.parametrize("connector", ["paystack-pay", "send-money", "airtime"])
    async def test_one_kobo_is_refused_with_the_smallest_amount(self, connector):
        stack = make_stack()
        tool, args = self.calls()[connector]
        made = await stack.call(
            connector,
            tool,
            **{
                **args,
                "amount_kobo": 1,
                "amount_as_user_said": "1 kobo",
                "idempotency_key": key("floor-tool"),
            },
        )
        assert made["isError"] is True and "structuredContent" not in made
        assert text_of(made).startswith("AMOUNT_TOO_SMALL: The smallest amount is ₦50.")
        assert await stack.count("quotes") == 0

    @pytest.mark.parametrize("connector", ["paystack-pay", "send-money", "airtime"])
    async def test_the_floor_itself_is_quoted(self, connector):
        stack = make_stack()
        tool, args = self.calls()[connector]
        made = await stack.call(
            connector,
            tool,
            **{**args, "amount_kobo": 5_000, "amount_as_user_said": "50", "idempotency_key": key("floor-ok")},
        )
        assert quote_of(made)["amount"]["display"] == "₦50"
