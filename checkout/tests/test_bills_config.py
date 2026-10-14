# SPDX-License-Identifier: AGPL-3.0-or-later
"""Where bills are offered and what they cost (docs/commerce.md, "Money"): the television and electricity
merchants exist only while VTpass is simulated or in its sandbox, as every use of VTpass here does, and 234's
service fee is a setting of the owner's whose default is none."""

import pytest

from checkout.commerce.directory import DirectoryProvider
from checkout.commerce.registry import Providers
from checkout.commerce.vtpass_provider import OFFERED_MODES, VtpassProvider, bill_providers
from checkout.config import Settings
from checkout.errors import ConfigError
from tests.commerce_support import refusal
from tests.support import make_stack


def load(**env: str) -> Settings:
    return Settings.from_env({"APPROVAL_SECRET": "x-not-real", **env}.get)


class TestWhereBillsAreOffered:
    @pytest.mark.parametrize("mode", ["simulated", "sandbox"])
    def test_with_vtpass_simulated_or_in_its_sandbox(self, stack, mode):
        api = stack.app.contexts["airtime"].vtpass
        (provider,) = bill_providers(stack.db, api, mode)
        assert isinstance(provider, VtpassProvider) and OFFERED_MODES == ("simulated", "sandbox")

    @pytest.mark.parametrize("mode", ["live", "production", "", "test"])
    def test_with_any_other_mode_there_is_no_bills_provider_and_building_one_is_refused(self, stack, mode):
        api = stack.app.contexts["airtime"].vtpass
        assert bill_providers(stack.db, api, mode) == ()
        with pytest.raises(ValueError, match="not offered"):
            VtpassProvider(stack.db, api, mode)

    async def test_without_the_provider_the_television_and_electricity_merchants_are_not_in_the_directory(
        self, stack
    ):
        providers = Providers(DirectoryProvider(stack.db, stack.clock))
        assert await refusal(providers.merchant("dstv")) == "MERCHANT_NOT_FOUND"
        assert await refusal(providers.merchant("ikeja-electric")) == "MERCHANT_NOT_FOUND"
        assert {m.category for m in await providers.merchants()}.isdisjoint({"tv", "electricity"})

    async def test_with_the_provider_they_are_listed_as_live_merchants_that_check_accounts(self, stack):
        merchants = {m.id: m for m in await stack.app.contexts["merchants"].providers.merchants()}
        assert {i for i, m in merchants.items() if m.category == "tv"} == {
            "dstv", "gotv", "startimes", "showmax",
        }  # fmt: skip
        assert sum(m.category == "electricity" for m in merchants.values()) == 12
        bills = [m for m in merchants.values() if m.provider == "vtpass"]
        assert all(m.status == "live" and not m.requires_link and not m.has_maximum for m in bills)
        assert {m.id for m in bills if not m.checks_account} == {"showmax"}

    async def test_the_merchants_state_no_most_and_a_least_no_lower_than_the_floor(self, stack):
        from checkout.amount_floor import MINIMUM_KOBO

        for merchant in await stack.app.contexts["merchants"].providers.merchants():
            if merchant.provider == "vtpass":
                assert merchant.min_kobo == MINIMUM_KOBO and merchant.has_maximum is False


class TestTheServiceFee:
    def test_is_none_unless_the_owner_sets_one(self):
        assert load().bills_service_fee_kobo == 0

    @pytest.mark.parametrize(("value", "kobo"), [("0", 0), ("25000", 25_000), (" 500 ", 500)])
    def test_is_read_in_whole_kobo(self, value, kobo):
        assert load(BILLS_SERVICE_FEE_KOBO=value).bills_service_fee_kobo == kobo

    @pytest.mark.parametrize("value", ["-1", "2.5", "abc", "₦250"])
    def test_that_is_not_a_whole_number_of_kobo_stops_the_worker_starting(self, value):
        with pytest.raises(ConfigError, match="BILLS_SERVICE_FEE_KOBO"):
            load(BILLS_SERVICE_FEE_KOBO=value)

    async def test_reaches_the_quote_as_a_line_of_its_own(self):
        from tests.bills_support import renewal_quote
        from tests.connector_support import quote_of

        stack = make_stack(bills_service_fee_kobo=10_000)
        fees = quote_of(await renewal_quote(stack))["details"]["fees"]
        assert fees == [{"label": "Service fee", "amount": "₦100"}]
