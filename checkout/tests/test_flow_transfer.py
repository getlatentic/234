# SPDX-License-Identifier: AGPL-3.0-or-later
"""The transfer flow, ported from the TypeScript demo's transfer-flow.test.ts, with the races and crash
points D1 without transactions makes possible."""

import asyncio
from dataclasses import replace

import pytest

from checkout.config import SimulatorSettings
from checkout.errors import DomainError
from checkout.flows.transfer import TransferFlow
from checkout.paystack.api import PaystackError, TransferOutcome
from checkout.paystack.sim import SIMULATED_OTP
from tests.support import PaystackOverride, make_stack

_counter = 0


def quote_input(**over):
    global _counter
    _counter += 1
    return {
        "account_number": "0000000000",
        "bank_code": "057",
        "amount_kobo": 2_500_000,
        "amount_as_user_said": "₦25,000",
        "narration": "Rent share",
        "idempotency_key": f"transfer-key-{_counter:04d}",
        **over,
    }


async def code_of(work) -> str:
    try:
        await work
    except DomainError as error:
        return error.code
    return "none"


def approve(flow, issued, amount=2_500_000):
    return flow.approve(issued.quote["id"], issued.approval_token, amount)


def flow_with(stack, **replacements) -> tuple[TransferFlow, PaystackOverride]:
    paystack = PaystackOverride(stack.app.contexts["send-money"].paystack, **replacements)
    return TransferFlow(replace(stack.app.contexts["send-money"], paystack=paystack)), paystack


class TestMakingATransferQuote:
    async def test_shows_the_account_name_the_bank_gave_not_one_the_model_wrote(self, stack):
        issued = await stack.transfers.create_quote(**quote_input())
        q = issued.quote
        assert q["phase"] == "awaiting_approval"
        assert q["amount"] == {"kobo": 2_500_000, "display": "₦25,000"}
        assert (q["description"], q["merchant"]) == ("Rent share", "PAYSTACK TEST ACCOUNT")
        assert q["details"] == {
            "kind": "transfer",
            "recipientName": "PAYSTACK TEST ACCOUNT",
            "bankName": "Zenith Bank",
            "accountMasked": "******0000",
        }
        assert "0000000000" not in str(q)

    async def test_records_the_quote_in_the_audit_log_with_the_account_masked(self, stack):
        await stack.transfers.create_quote(**quote_input(account_number="0123456789", bank_code="058"))
        log = "\n".join(stack.audit_lines)
        assert '"account_masked": "******6789"' in log
        assert "0123456789" not in log

    async def test_accepts_spaces_in_the_account_number(self, stack):
        issued = await stack.transfers.create_quote(
            **quote_input(account_number="0123 4567 89", bank_code="058")
        )
        details = issued.quote["details"]
        assert (details["recipientName"], details["bankName"]) == (
            "SIMULATED ACCOUNT 6789",
            "Guaranty Trust Bank",
        )

    @pytest.mark.parametrize(
        "over",
        [{"account_number": "12345"}, {"account_number": "01234abcde"}, {"bank_code": "Zenith"}],
        ids=["a short account number", "letters in the account", "a bank name instead of a code"],
    )
    async def test_refuses_bad_input(self, stack, over):
        assert await code_of(stack.transfers.create_quote(**quote_input(**over))) == "INVALID_INPUT"

    async def test_refuses_an_account_the_bank_cannot_resolve_and_makes_no_quote(self, stack):
        refused = stack.transfers.create_quote(**quote_input(account_number="9999123456"))
        assert await code_of(refused) == "PROVIDER_ERROR"
        assert await stack.count("quotes") == 0

    async def test_refuses_an_amount_that_does_not_match_the_users_words_before_calling_paystack(self, stack):
        flow, paystack = flow_with(stack)
        assert await code_of(flow.create_quote(**quote_input(amount_kobo=250_000))) == "AMOUNT_MISMATCH"
        assert paystack.calls == {}

    async def test_refuses_an_amount_over_the_limit_before_calling_paystack(self, stack):
        flow, paystack = flow_with(stack)
        refused = flow.create_quote(**quote_input(amount_kobo=6_000_000, amount_as_user_said="60k"))
        assert await code_of(refused) == "LIMIT_PER_PAYMENT"
        assert paystack.calls == {}

    async def test_replays_a_repeated_key_without_calling_paystack_again(self, stack):
        first = quote_input()
        a = await stack.transfers.create_quote(**first)
        flow, paystack = flow_with(stack)
        b = await flow.create_quote(**first)
        assert (b.replayed, b.quote["id"]) == (True, a.quote["id"])
        assert paystack.calls == {}
        changed = flow.create_quote(**{**first, "amount_kobo": 100_000, "amount_as_user_said": "1k"})
        assert await code_of(changed) == "IDEMPOTENCY_CONFLICT"

    async def test_refuses_a_bad_idempotency_key_before_calling_paystack(self, stack):
        flow, paystack = flow_with(stack)
        assert await code_of(flow.create_quote(**quote_input(idempotency_key="short"))) == "INVALID_INPUT"
        assert paystack.calls == {}

    async def test_the_same_key_asked_together_makes_one_quote_and_one_recipient(self, stack):
        first = quote_input()
        issued = await asyncio.gather(*[stack.transfers.create_quote(**first) for _ in range(10)])
        assert len({i.quote["id"] for i in issued}) == 1
        assert await stack.count("quotes") == 1
        assert await stack.count("sim_recipients") == 1


def named(bank, **over):
    return quote_input(bank=bank, bank_code=None, **over)


class TestChoosingTheBankByName:
    async def asked_of_paystack(self, stack):
        looked_up = []

        async def resolve(lookup):
            looked_up.append(lookup)
            return "SIMULATED ACCOUNT"

        flow, paystack = flow_with(stack, resolve_account=resolve)
        return flow, paystack, looked_up

    @pytest.mark.parametrize(
        ("said", "code", "shown"),
        [
            ("GTB", "058", "Guaranty Trust Bank"),
            ("guaranty trust", "058", "Guaranty Trust Bank"),
            ("Access", "044", "Access Bank"),
            ("UBA", "033", "United Bank For Africa"),
            ("opay", "999992", "OPay Digital Services Limited (OPay)"),
            ("Kuda", "50211", "Kuda Bank"),
            ("ALAT", "035A", "ALAT by WEMA"),
        ],
    )
    async def test_the_name_becomes_the_banks_code_and_the_card_shows_the_banks_name(
        self, stack, said, code, shown
    ):
        flow, _, looked_up = await self.asked_of_paystack(stack)
        issued = await flow.create_quote(**named(said, account_number="0123456789"))
        assert [(lookup.account_number, lookup.bank_code) for lookup in looked_up] == [("0123456789", code)]
        assert issued.quote["details"]["bankName"] == shown
        assert issued.quote["details"]["recipientName"] == "SIMULATED ACCOUNT"

    async def test_a_bank_the_person_named_and_its_own_code_agree(self, stack):
        issued = await stack.transfers.create_quote(**quote_input(bank="Zenith", bank_code="057"))
        assert issued.quote["details"]["bankName"] == "Zenith Bank"

    async def test_a_code_alone_still_works_for_a_client_that_holds_one(self, stack):
        issued = await stack.transfers.create_quote(**quote_input(bank_code="058"))
        assert issued.quote["details"]["bankName"] == "Guaranty Trust Bank"

    async def test_a_code_contradicting_the_named_bank_is_refused_before_paystack_is_asked(self, stack):
        flow, paystack, looked_up = await self.asked_of_paystack(stack)
        refused = flow.create_quote(**quote_input(bank="GTB", bank_code="044"))
        with pytest.raises(DomainError) as error:
            await refused
        assert error.value.code == "BANK_MISMATCH"
        assert "Access Bank" in error.value.message and "Guaranty Trust Bank" in error.value.message
        assert paystack.calls == {} and looked_up == [] and await stack.count("quotes") == 0

    async def test_a_bank_that_is_not_on_the_list_is_refused_with_the_nearest_and_nothing_is_made(
        self, stack
    ):
        flow, paystack, _ = await self.asked_of_paystack(stack)
        with pytest.raises(DomainError) as error:
            await flow.create_quote(**named("Acess Bank"))
        assert error.value.code == "BANK_UNKNOWN"
        assert "Access Bank" in error.value.message and "Ask the person which bank" in error.value.message
        assert paystack.calls == {} and await stack.count("quotes") == 0

    async def test_a_bank_that_fits_several_is_refused_naming_up_to_three(self, stack):
        flow, paystack, _ = await self.asked_of_paystack(stack)
        with pytest.raises(DomainError) as error:
            await flow.create_quote(**named("First"))
        assert error.value.code == "BANK_AMBIGUOUS"
        assert "First Bank of Nigeria" in error.value.message
        assert error.value.message.count(" or ") == 1 and error.value.message.count(",") <= 2
        assert paystack.calls == {} and await stack.count("quotes") == 0

    @pytest.mark.parametrize("over", [{"bank": None, "bank_code": None}, {"bank": "  ", "bank_code": None}])
    async def test_no_bank_at_all_is_refused_and_says_to_ask(self, stack, over):
        with pytest.raises(DomainError) as error:
            await stack.transfers.create_quote(**quote_input(**over))
        assert error.value.code == "INVALID_INPUT" and "ask which bank" in error.value.message

    async def test_a_code_nobody_lists_and_that_is_not_numeric_is_refused(self, stack):
        assert (
            await code_of(stack.transfers.create_quote(**quote_input(bank_code="Zenith"))) == "INVALID_INPUT"
        )

    async def test_the_same_request_by_name_and_by_code_is_one_request_to_the_ledger(self, stack):
        by_name = quote_input(bank="Zenith", bank_code=None)
        first = await stack.transfers.create_quote(**by_name)
        again = await stack.transfers.create_quote(**{**by_name, "bank": None, "bank_code": "057"})
        assert (again.replayed, again.quote["id"]) == (True, first.quote["id"])


class TestApprovingATransfer:
    async def test_sends_it_and_shows_a_receipt_with_the_account_masked(self, stack):
        issued = await stack.transfers.create_quote(**quote_input())
        done = await approve(stack.transfers, issued)
        assert (done["phase"], done["receipt"]["title"]) == ("succeeded", "Transfer sent")
        for line in (
            {"label": "Amount", "value": "₦25,000"},
            {"label": "To", "value": "PAYSTACK TEST ACCOUNT"},
            {"label": "Bank", "value": "Zenith Bank"},
            {"label": "Account", "value": "******0000"},
        ):
            assert line in done["receipt"]["lines"]
        reference = next(line["value"] for line in done["receipt"]["lines"] if line["label"] == "Reference")
        assert reference == f"trf-{issued.quote['id']}"
        log = "\n".join(stack.audit_lines)
        assert "0000000000" not in log and "transfer.settled" in log

    async def test_refuses_without_the_cards_token_and_when_the_card_showed_another_amount(self, stack):
        issued = await stack.transfers.create_quote(**quote_input())
        assert await code_of(stack.transfers.approve(issued.quote["id"], "x", 2_500_000)) == "APPROVAL_DENIED"
        assert await code_of(approve(stack.transfers, issued, 250_000)) == "AMOUNT_MISMATCH"
        assert (await stack.ledger.get(issued.quote["id"])).state == "open"

    async def test_does_not_send_twice_for_a_repeated_approval(self, stack):
        issued = await stack.transfers.create_quote(**quote_input())
        flow, paystack = flow_with(stack)
        await approve(flow, issued)
        again = await approve(flow, issued)
        assert again["phase"] == "succeeded"
        assert paystack.calls["initiate_transfer"] == 1
        assert (await stack.ledger.budget()).spent_today_kobo == 2_500_000

    async def test_sends_once_however_many_approve_together(self, stack):
        issued = await stack.transfers.create_quote(**quote_input())
        flow, paystack = flow_with(stack)
        views = await asyncio.gather(*[approve(flow, issued) for _ in range(15)])
        assert paystack.calls["initiate_transfer"] == 1
        assert {v["phase"] for v in views} <= {"processing", "succeeded"}
        assert (await flow.verify(issued.quote["id"]))["phase"] == "succeeded"
        assert await stack.count("sim_transfers") == 1

    async def test_keeps_the_approval_when_paystack_cannot_be_reached_and_retries_with_the_same_reference(
        self, stack
    ):
        issued = await stack.transfers.create_quote(**quote_input())
        real = stack.app.contexts["send-money"].paystack
        references, attempts = [], []

        async def flaky(request):
            references.append(request.reference)
            attempts.append(1)
            if len(attempts) == 1:
                raise PaystackError("Paystack could not be reached.", retryable=True)
            return await real.initiate_transfer(request)

        flow, _ = flow_with(stack, initiate_transfer=flaky)
        assert await code_of(approve(flow, issued)) == "PROVIDER_ERROR"
        assert (await stack.ledger.get(issued.quote["id"])).state == "approved"
        assert (await stack.ledger.budget()).spent_today_kobo == 2_500_000
        assert (await approve(flow, issued))["phase"] == "succeeded"
        assert len(references) == 2 and references[0] == references[1]

    async def test_a_transfer_paystack_took_but_the_answer_of_which_was_lost_is_found_not_sent_again(
        self, stack
    ):
        issued = await stack.transfers.create_quote(**quote_input())
        real = stack.app.contexts["send-money"].paystack

        async def lose_the_answer(request):
            await real.initiate_transfer(request)
            raise PaystackError("Paystack could not be reached.", retryable=True)

        flow, paystack = flow_with(stack, initiate_transfer=lose_the_answer)
        assert await code_of(approve(flow, issued)) == "PROVIDER_ERROR"
        assert await stack.count("sim_transfers") == 1
        done = await approve(flow, issued)
        assert done["phase"] == "succeeded"
        assert paystack.calls["initiate_transfer"] == 1, "found by its reference, not sent again"
        assert await stack.count("sim_transfers") == 1

    async def test_an_approval_that_never_started_the_transfer_is_finished_by_the_next_status_check(
        self, stack
    ):
        issued = await stack.transfers.create_quote(**quote_input())
        await stack.ledger.claim_approval(issued.quote["id"], "send-money")
        assert (await stack.transfers.verify(issued.quote["id"]))["phase"] == "succeeded"
        assert await stack.count("sim_transfers") == 1

    async def test_a_worker_lost_mid_send_is_recovered_once_its_step_lock_goes_stale(self, stack):
        issued = await stack.transfers.create_quote(**quote_input())
        real = stack.app.contexts["send-money"].paystack

        async def evicted(request):
            await real.initiate_transfer(request)
            raise asyncio.CancelledError  # an evicted Worker runs no handler

        flow, _ = flow_with(stack, initiate_transfer=evicted)
        with pytest.raises(asyncio.CancelledError):
            await approve(flow, issued)
        assert (await approve(stack.transfers, issued))["phase"] == "processing", (
            "the step lock is still held"
        )
        stack.clock.advance(31)
        assert (await approve(stack.transfers, issued))["phase"] == "succeeded"
        assert await stack.count("sim_transfers") == 1

    async def test_lets_go_of_the_step_when_something_unexpected_goes_wrong_and_finds_the_transfer_next_time(
        self, stack
    ):
        issued = await stack.transfers.create_quote(**quote_input())
        real = stack.app.contexts["send-money"].paystack

        async def breaks_after_sending(request):
            await real.initiate_transfer(request)
            raise RuntimeError("unexpected")

        flow, _ = flow_with(stack, initiate_transfer=breaks_after_sending)
        with pytest.raises(RuntimeError):
            await approve(flow, issued)
        assert (await approve(stack.transfers, issued))["phase"] == "succeeded"
        assert await stack.count("sim_transfers") == 1

    async def test_fails_the_quote_and_frees_the_spend_when_paystack_refuses_the_transfer(self, stack):
        issued = await stack.transfers.create_quote(**quote_input())

        async def refuse(request):
            raise PaystackError("Your balance is not enough to fulfil this request", False, 400)

        flow, _ = flow_with(stack, initiate_transfer=refuse)
        view = await approve(flow, issued)
        assert view["phase"] == "failed"
        assert "Your balance is not enough" in view["message"]
        assert (await stack.ledger.budget()).spent_today_kobo == 0

    async def test_follows_a_pending_transfer_until_paystack_says_it_is_done(self, stack):
        issued = await stack.transfers.create_quote(**quote_input())
        status = ["pending"]

        async def initiate(request):
            return TransferOutcome("pending", "TRF_slow", request.reference, request.amount_kobo)

        async def verify(reference):
            return TransferOutcome(status[0], "TRF_slow", reference, 2_500_000)

        flow, _ = flow_with(stack, initiate_transfer=initiate, verify_transfer=verify)
        first = await approve(flow, issued)
        assert (first["phase"], first["poll"]) == ("processing", True)
        assert (await flow.verify(issued.quote["id"]))["phase"] == "processing"
        status[0] = "success"
        assert (await flow.verify(issued.quote["id"]))["phase"] == "succeeded"

    async def test_marks_a_transfer_for_a_different_amount_than_the_quote_as_a_refund_due(self, stack):
        issued = await stack.transfers.create_quote(**quote_input())

        async def odd(request):
            return TransferOutcome("success", "TRF_odd", request.reference, 100)

        flow, _ = flow_with(stack, initiate_transfer=odd)
        view = await approve(flow, issued)
        assert view["phase"] == "attention"
        assert "₦1 for a ₦25,000 quote" in view["message"]

    @pytest.mark.parametrize("status", ["failed", "reversed"])
    async def test_a_failed_or_reversed_transfer_is_failed_and_frees_the_spend(self, stack, status):
        issued = await stack.transfers.create_quote(**quote_input())

        async def outcome(request):
            return TransferOutcome(status, "TRF_x", request.reference, request.amount_kobo)

        flow, _ = flow_with(stack, initiate_transfer=outcome)
        assert (await approve(flow, issued))["phase"] == "failed"
        assert (await stack.ledger.budget()).spent_today_kobo == 0


class TestAnAccountThatCannotMakePayouts:
    async def test_fails_closed_keeps_nothing_reserved_and_never_falls_back_to_the_simulator(self, stack):
        issued = await stack.transfers.create_quote(**quote_input())

        async def refuse(request):
            raise PaystackError("You cannot initiate third party payouts as a starter business", False, 400)

        flow, paystack = flow_with(stack, initiate_transfer=refuse)
        view = await approve(flow, issued)
        assert (view["phase"], view["poll"]) == ("unavailable", False)
        assert "Paystack test transfers are not enabled on this account (Starter Business)" in view["message"]
        assert "SEND_MONEY_MODE=simulated" in view["message"]
        assert "fail" not in view["message"].lower() and "error" not in view["message"].lower()
        assert (await stack.ledger.budget()).spent_today_kobo == 0
        assert paystack.calls["initiate_transfer"] == 1
        assert await stack.count("sim_transfers") == 0
        assert "payouts unavailable" in "\n".join(stack.audit_lines)

    async def test_the_simulator_refuses_as_paystack_does_when_asked_to(self):
        stack = make_stack(simulator=SimulatorSettings(payouts_refused=True))
        issued = await stack.transfers.create_quote(**quote_input())
        assert (await approve(stack.transfers, issued))["phase"] == "unavailable"

    async def test_gives_another_refusal_from_paystack_its_own_words_as_a_failed_transfer(self, stack):
        issued = await stack.transfers.create_quote(**quote_input())

        async def refuse(request):
            raise PaystackError("Invalid recipient", False, 400)

        flow, _ = flow_with(stack, initiate_transfer=refuse)
        view = await approve(flow, issued)
        assert view["phase"] == "failed" and "Invalid recipient" in view["message"]


class TestAPaystackAccountThatAsksForATransferOtp:
    @pytest.fixture
    def otp_stack(self):
        return make_stack(simulator=SimulatorSettings(transfer_otp=True))

    async def test_shows_what_to_do_refuses_a_wrong_code_and_finishes_with_the_right_one(self, otp_stack):
        flow = otp_stack.transfers
        issued = await flow.create_quote(**quote_input())
        waiting = await approve(flow, issued)
        assert (waiting["phase"], waiting["poll"]) == ("awaiting_otp", False)
        assert SIMULATED_OTP in waiting["otpHint"]
        assert await code_of(flow.submit_otp(issued.quote["id"], "000000")) == "OTP_REJECTED"
        assert (await otp_stack.ledger.get(issued.quote["id"])).state == "approved"
        assert (await flow.submit_otp(issued.quote["id"], SIMULATED_OTP))["phase"] == "succeeded"

    async def test_does_not_keep_or_log_the_code(self, otp_stack):
        flow = otp_stack.transfers
        issued = await flow.create_quote(**quote_input())
        await approve(flow, issued)
        await flow.submit_otp(issued.quote["id"], SIMULATED_OTP)
        quote = await otp_stack.ledger.get(issued.quote["id"])
        assert SIMULATED_OTP not in str(quote)
        assert SIMULATED_OTP not in "\n".join(otp_stack.audit_lines)

    async def test_finalizes_once_however_many_submit_together(self, otp_stack):
        issued = await otp_stack.transfers.create_quote(**quote_input())
        flow, paystack = flow_with(otp_stack)
        await approve(flow, issued)
        results = await asyncio.gather(
            *[flow.submit_otp(issued.quote["id"], SIMULATED_OTP) for _ in range(10)], return_exceptions=True
        )
        assert paystack.calls["finalize_transfer"] == 1
        assert sum(isinstance(r, dict) for r in results) == 1
        assert (await flow.verify(issued.quote["id"]))["phase"] == "succeeded"

    async def test_refuses_a_code_for_a_transfer_that_is_not_waiting_for_one_and_a_malformed_code(
        self, stack, otp_stack
    ):
        done = await stack.transfers.create_quote(**quote_input())
        await approve(stack.transfers, done)
        assert await code_of(stack.transfers.submit_otp(done.quote["id"], "123456")) == "NOT_VERIFIABLE"

        issued = await otp_stack.transfers.create_quote(**quote_input())
        await approve(otp_stack.transfers, issued)
        assert await code_of(otp_stack.transfers.submit_otp(issued.quote["id"], "12ab")) == "INVALID_INPUT"


async def test_lets_the_person_decline(stack):
    issued = await stack.transfers.create_quote(**quote_input())
    assert (await stack.transfers.decline(issued.quote["id"], issued.approval_token))["phase"] == "declined"
