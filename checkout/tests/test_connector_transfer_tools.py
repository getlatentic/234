# SPDX-License-Identifier: AGPL-3.0-or-later
"""The send-money tools through JSON-RPC, ported from the TypeScript demo's connector tests."""

from checkout.config import SimulatorSettings
from checkout.paystack.sim import SIMULATED_OTP
from tests.connector_support import approve_args, key, listed, quote_of, text_of
from tests.support import make_stack


class TestTransferTools:
    def quote_args(self, **over):
        return {
            "account_number": "0000000000",
            "bank_code": "057",
            "amount_kobo": 2_500_000,
            "amount_as_user_said": "25k",
            "narration": "Rent share",
            "idempotency_key": key("mcp-transfer"),
            **over,
        }

    async def test_names_the_account_holder_from_the_bank_lookup_and_keeps_the_account_number_from_the_model(
        self, stack
    ):
        made = await stack.call("send-money", "create_transfer_quote", **self.quote_args())
        assert "isError" not in made
        details = quote_of(made)["details"]
        assert (details["kind"], details["recipientName"], details["bankName"]) == (
            "transfer", "PAYSTACK TEST ACCOUNT", "Zenith Bank",
        )  # fmt: skip
        assert "PAYSTACK TEST ACCOUNT" in text_of(made) and "0000000000" not in text_of(made)

    async def test_sends_after_approval_and_shows_a_receipt(self, stack):
        made = await stack.call("send-money", "create_transfer_quote", **self.quote_args())
        done = await stack.call("send-money", "approve_quote", **approve_args(made))
        assert (quote_of(done)["phase"], quote_of(done)["receipt"]["title"]) == ("succeeded", "Transfer sent")

    async def test_walks_through_the_one_time_code_when_the_account_asks_for_it(self):
        stack = make_stack(simulator=SimulatorSettings(transfer_otp=True))
        made = await stack.call("send-money", "create_transfer_quote", **self.quote_args())
        waiting = await stack.call("send-money", "approve_quote", **approve_args(made))
        assert quote_of(waiting)["phase"] == "awaiting_otp"
        assert SIMULATED_OTP in quote_of(waiting)["otpHint"]
        quote_id = quote_of(made)["id"]
        wrong = await stack.call("send-money", "submit_otp", quote_id=quote_id, otp="000000")
        assert text_of(wrong).startswith("OTP_REJECTED")
        done = await stack.call("send-money", "submit_otp", quote_id=quote_id, otp=SIMULATED_OTP)
        assert quote_of(done)["phase"] == "succeeded"

    async def test_tells_the_model_and_the_card_without_alarm_when_the_account_cannot_make_payouts(self):
        stack = make_stack(simulator=SimulatorSettings(payouts_refused=True))
        made = await stack.call("send-money", "create_transfer_quote", **self.quote_args())
        result = await stack.call("send-money", "approve_quote", **approve_args(made))
        assert "isError" not in result and quote_of(result)["phase"] == "unavailable"
        status = await stack.call("send-money", "get_quote_status", quote_id=quote_of(made)["id"])
        assert "Paystack test transfers are not enabled on this account (Starter Business)" in text_of(status)
        assert "SEND_MONEY_MODE=simulated" in text_of(status)

    async def test_refuses_an_account_number_that_is_not_ten_digits(self, stack):
        result = await stack.call(
            "send-money", "create_transfer_quote", **self.quote_args(account_number="12345678901")
        )
        assert text_of(result).startswith("INVALID_INPUT")

    async def test_the_card_shows_the_mode_the_owner_chose_and_why(self):
        from checkout.config import PaystackSettings

        secret = "sk_test_" + "abcdefgh12345678"
        paystack = PaystackSettings("test", secret, {"send-money": "simulated"})
        stack = make_stack(paystack=paystack)
        made = await stack.call("send-money", "create_transfer_quote", **self.quote_args())
        assert quote_of(made)["mode"]["label"] == (
            "Simulated: no money moves (this Paystack account cannot make payouts)"
        )


class TestTheBankByName:
    def by_name(self, bank, **over):
        args = TestTransferTools().quote_args(account_number="0123456789")
        return {**{k: v for k, v in args.items() if k != "bank_code"}, "bank": bank, **over}

    async def test_a_bank_named_the_way_people_say_it_is_quoted_and_the_card_shows_its_name(self, stack):
        made = await stack.call("send-money", "create_transfer_quote", **self.by_name("GTB"))
        assert "isError" not in made
        assert quote_of(made)["details"]["bankName"] == "Guaranty Trust Bank"

    async def test_an_unknown_bank_is_refused_with_the_nearest_named_and_no_card(self, stack):
        made = await stack.call("send-money", "create_transfer_quote", **self.by_name("Acess Bank"))
        assert made["isError"] is True and "structuredContent" not in made
        assert text_of(made).startswith("BANK_UNKNOWN") and "Access Bank" in text_of(made)

    async def test_an_ambiguous_bank_is_refused_naming_banks_to_ask_about(self, stack):
        made = await stack.call("send-money", "create_transfer_quote", **self.by_name("First"))
        assert text_of(made).startswith("BANK_AMBIGUOUS")
        assert "First Bank of Nigeria" in text_of(made) and "First City Monument Bank" in text_of(made)

    async def test_a_code_that_contradicts_the_named_bank_is_refused(self, stack):
        made = await stack.call("send-money", "create_transfer_quote", **self.by_name("GTB", bank_code="044"))
        assert text_of(made).startswith("BANK_MISMATCH")

    async def test_neither_a_bank_nor_a_code_is_refused(self, stack):
        args = self.by_name("GTB")
        del args["bank"]
        made = await stack.call("send-money", "create_transfer_quote", **args)
        assert made["isError"] is True and "ask which bank" in text_of(made)

    async def test_the_schema_takes_the_bank_name_and_keeps_the_code_for_clients_that_send_it(self, stack):
        schema = (await listed(stack, "send-money"))["create_transfer_quote"]["inputSchema"]
        assert {"bank", "bank_code"} <= set(schema["properties"])
        assert "bank_code" not in schema["required"] and "bank" not in schema["required"]
        assert schema["properties"]["bank_code"]["x-model-hidden"] is True
        assert schema["x-model-required"] == ["bank"]
