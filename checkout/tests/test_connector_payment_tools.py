# SPDX-License-Identifier: AGPL-3.0-or-later
"""The paystack-pay tools through JSON-RPC, ported from the TypeScript demo's connector tests."""

import json

from tests.connector_support import approve_args, key, quote_of, text_of


class TestPaymentTools:
    def quote_args(self, **over):
        return {
            "amount_kobo": 500_000,
            "amount_as_user_said": "five thousand naira",
            "description": "Lunch at Demo Kitchen",
            "merchant": "Demo Kitchen",
            "idempotency_key": key("mcp-payment"),
            **over,
        }

    async def test_returns_the_quote_the_token_only_in_meta_and_a_text_the_model_can_act_on(self, stack):
        result = await stack.call("paystack-pay", "create_payment_quote", **self.quote_args())
        assert "isError" not in result
        q = quote_of(result)
        assert (q["phase"], q["amount"]["display"], q["mode"]["simulated"]) == (
            "awaiting_approval",
            "₦5,000",
            True,
        )
        token = result["_meta"]["approvalToken"]
        assert len(token) == 64
        assert token not in text_of(result) and token not in json.dumps(result["structuredContent"])
        for expected in ("₦5,000", "Simulated: no money moves", "You cannot approve it"):
            assert expected in text_of(result)

    async def test_refuses_an_amount_that_does_not_match_with_a_message_the_model_can_act_on(self, stack):
        result = await stack.call(
            "paystack-pay", "create_payment_quote", **self.quote_args(amount_kobo=50_000_000)
        )
        assert (
            result["isError"] is True and "AMOUNT_MISMATCH" in text_of(result) and "₦5,000" in text_of(result)
        )

    async def test_refuses_a_field_the_schema_does_not_have(self, stack):
        result = await stack.call(
            "paystack-pay", "create_payment_quote", **self.quote_args(card_number="4084084084084081")
        )
        assert result["isError"] is True

    async def test_refuses_a_card_number_in_any_text_field_and_records_the_refusal_without_the_number(
        self, stack
    ):
        result = await stack.call(
            "paystack-pay",
            "create_payment_quote",
            **self.quote_args(description="pay with 4084 0840 8408 4081"),
        )
        assert result["isError"] is True and text_of(result).startswith("CARD_DATA_REFUSED")
        log = "\n".join(stack.audit_lines)
        assert "guard.card_data_refused" in log and "4084" not in log

    async def test_refuses_an_amount_over_the_per_payment_limit(self, stack):
        result = await stack.call(
            "paystack-pay",
            "create_payment_quote",
            **self.quote_args(amount_kobo=6_000_000, amount_as_user_said="60k"),
        )
        assert text_of(result).startswith("LIMIT_PER_PAYMENT")

    async def test_refuses_to_approve_without_the_cards_token_and_the_quote_stays_open(self, stack):
        made = await stack.call("paystack-pay", "create_payment_quote", **self.quote_args())
        denied = await stack.call(
            "paystack-pay", "approve_quote", **approve_args(made, approval_token="not-the-token")
        )
        assert text_of(denied).startswith("APPROVAL_DENIED")
        status = await stack.call("paystack-pay", "get_quote_status", quote_id=quote_of(made)["id"])
        assert quote_of(status)["phase"] == "awaiting_approval"

    async def test_runs_the_whole_path_through_the_tools_quote_approve_pay_verify_status(self, stack):
        made = await stack.call("paystack-pay", "create_payment_quote", **self.quote_args())
        approved = await stack.call("paystack-pay", "approve_quote", **approve_args(made))
        assert quote_of(approved)["phase"] == "awaiting_checkout"
        url = quote_of(approved)["checkoutUrl"]
        assert url.startswith("http://localhost:8787/sim/checkout/qt-")
        await stack.complete_checkout(url, "success")
        verified = await stack.call("paystack-pay", "verify_quote", quote_id=quote_of(made)["id"])
        assert quote_of(verified)["phase"] == "succeeded"
        assert quote_of(verified)["receipt"]["title"] == "Payment received"
        status = await stack.call("paystack-pay", "get_quote_status", quote_id=quote_of(made)["id"])
        assert "succeeded" in text_of(status) and "localhost" not in text_of(status)

    async def test_does_not_hand_the_model_the_checkout_link_when_it_asks_for_the_status(self, stack):
        made = await stack.call("paystack-pay", "create_payment_quote", **self.quote_args())
        approved = await stack.call("paystack-pay", "approve_quote", **approve_args(made))
        assert quote_of(approved)["checkoutUrl"].startswith("http")
        status = await stack.call("paystack-pay", "get_quote_status", quote_id=quote_of(made)["id"])
        assert quote_of(status)["phase"] == "awaiting_checkout" and quote_of(status)["checkoutUrl"] is None
        assert "sim/checkout" not in json.dumps(status)

    async def test_refuses_an_approval_that_names_a_different_amount_than_the_quote(self, stack):
        made = await stack.call("paystack-pay", "create_payment_quote", **self.quote_args())
        denied = await stack.call(
            "paystack-pay", "approve_quote", **approve_args(made, displayed_amount_kobo=5_000)
        )
        assert text_of(denied).startswith("AMOUNT_MISMATCH")

    async def test_declines_with_the_token(self, stack):
        made = await stack.call("paystack-pay", "create_payment_quote", **self.quote_args())
        declined = await stack.call(
            "paystack-pay",
            "decline_quote",
            quote_id=quote_of(made)["id"],
            approval_token=made["_meta"]["approvalToken"],
        )
        assert quote_of(declined)["phase"] == "declined"

    async def test_returns_a_readable_error_for_an_unknown_quote(self, stack):
        result = await stack.call("paystack-pay", "get_quote_status", quote_id="qt-doesnotexist")
        assert result["isError"] is True and text_of(result).startswith("QUOTE_NOT_FOUND")

    async def test_a_connector_will_not_answer_for_another_connectors_quote(self, stack):
        made = await stack.call("paystack-pay", "create_payment_quote", **self.quote_args())
        result = await stack.call("airtime", "get_quote_status", quote_id=quote_of(made)["id"])
        assert text_of(result).startswith("WRONG_CONNECTOR")
