# SPDX-License-Identifier: AGPL-3.0-or-later
"""The bills provider's own guards, asked directly, beside the tools that reach them (commerce/vtpass_*.py,
commerce/binding.py): the account check a quote needs or does not, and the order the approval is bound to."""

from dataclasses import replace

from checkout.commerce.binding import quote_digest
from checkout.commerce.model import Basket, BasketLine
from checkout.owner import acting_for
from tests.bills_support import PHONE, SMARTCARD, bills, renewal_quote
from tests.commerce_support import refusal
from tests.connector_support import quote_of
from tests.support import ALICE


class TestPricing:
    async def test_prices_nothing_for_a_merchant_that_checks_accounts_without_a_check(self, stack):
        provider = bills(stack)
        dstv = await provider.merchant("dstv")
        basket = Basket((BasketLine("dstv-padi"),), None, {"smartcard": SMARTCARD, "phone": PHONE})
        assert await refusal(provider.price(dstv, basket, None)) == "ACCOUNT_CHECK_REQUIRED"

    async def test_prices_nothing_for_a_check_it_does_not_need(self, stack):
        provider = bills(stack)
        dstv, showmax = await provider.merchant("dstv"), await provider.merchant("showmax")
        found = await provider.check(dstv, {"smartcard": SMARTCARD})
        check = await stack.app.contexts["merchants"].checks.record(dstv, {"smartcard": SMARTCARD}, found)
        basket = Basket((BasketLine("showmax-mobile"),), None, {"phone": PHONE})
        assert await refusal(provider.price(showmax, basket, check)) == "ACCOUNT_CHECK_REQUIRED"


class TestTheApprovalIsBoundToWhatWillBeOrdered:
    async def test_a_quote_that_would_order_something_else_has_another_digest(self, stack):
        made = await renewal_quote(stack)
        with acting_for(ALICE):
            quote = await stack.app.contexts["merchants"].ledger.get(quote_of(made)["id"])
        order = {**quote.details["order"], "billers_code": "1"}
        other = replace(quote, details={**quote.details, "order": order})
        assert quote_digest(other) != quote_digest(quote)
