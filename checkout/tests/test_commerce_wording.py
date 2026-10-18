# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the model is told when it reads the directory, measured on the evaluation (evaluation/RESULTS.md,
"Merged stack phase"): the electricity lines say to ask only for what the person has not said, and a listing
that shows an Index merchant says when to use one."""

from checkout.commerce.listing import INDEX_RULE, merchant_listing
from checkout.commerce.model import Merchant
from tests.connector_support import text_of


async def browse(stack, **arguments) -> str:
    return text_of(await stack.call("merchants", "browse_merchants", **arguments))


def merchant(merchant_id: str, provider: str) -> Merchant:
    return Merchant(
        id=merchant_id,
        provider=provider,
        name="Power",
        category="electricity",
        status="live",
        requires_link=False,
        blurb="Electricity.",
        min_kobo=5000,
        max_kobo=10**13,
        fee_label="Fee",
        fee_kobo=0,
        checks_account=True,
        fields=(),
    )


class TestTheElectricityLines:
    async def test_a_line_says_to_ask_only_for_what_is_not_said(self, stack):
        lines = (await browse(stack, category="electricity")).splitlines()
        ikeja = next(line for line in lines if line.startswith("ikeja-electric |"))
        assert "ask only for what is not said" in ikeja
        assert "never assume it" not in ikeja
        assert ikeja.endswith("Needs meter_number, meter_type, phone, after check_account.")

    async def test_every_blurb_fits_the_table(self, stack):
        row = await stack.db.row(
            "SELECT MAX(length(blurb)) AS n FROM merchant WHERE category = 'electricity'"
        )
        assert 0 < row["n"] <= 300


class TestTheIndexRule:
    def test_a_listing_with_an_index_merchant_says_when_to_use_it(self):
        plain = merchant_listing([merchant("ikeja-electric", "vtpass")])
        with_index = merchant_listing(
            [merchant("ikeja-electric", "vtpass"), merchant("index:ikeja-electric", "index")]
        )
        assert INDEX_RULE not in plain
        assert INDEX_RULE in with_index
        assert "only when they ask for Index or Zap" in INDEX_RULE
