# SPDX-License-Identifier: AGPL-3.0-or-later
"""The scorer on the `bills-dev` split and on UNS-06 (docs/commerce.md): a DStv or electricity bill quoted for
an account that was checked first, the questions a missing smartcard, phone, meter type or company must get, a
wrong meter or smartcard that is refused and never quoted, an amount outside the limits, and the held-out case
whose answer changed when DSTV became a merchant: it was a decline, and it is a purchase."""

from evaluation.score import score_case

from .helpers import call, case, turn

CHECK = "ck-0123456789abcdef0123"
CARD = "1212121212"
PHONE = "08031234567"


def merchants(tool: str, arguments: dict, result: str = "ok", **kw):
    return {**call(tool, "merchants", arguments, result=result, **kw), "read": result}


def card(kobo: int = 1050000) -> dict:
    return {"tool": "create_quote", "quote_id": "q1", "kind": "basket", "amount_kobo": kobo, "merchant": "DStv"}


def scored(case_id: str, *records: dict):
    return score_case(case(case_id), list(records))


def kinds(result) -> list[str]:
    return [f.kind for f in result.findings]


def checked(merchant: str, fields: dict, holder: str = "ADEOLA BALOGUN"):
    return merchants("check_account", {"merchant_id": merchant, "fields": fields}, f"holder {holder}. check_id: {CHECK}")


def renewal(**over):
    arguments = {
        "merchant_id": "dstv",
        "lines": [{"offer_id": "renew"}],
        "fields": {"smartcard": CARD, "phone": PHONE},
        "check_id": CHECK,
        "idempotency_key": "k",
    }
    return merchants("create_quote", {**arguments, **over}, "Quote qt-1: ₦10,500 for Renew DStv Confam.")


REPLY = "The quote is ready: check the holder's name on the card and approve it."


class TestARenewal:
    def test_the_card_checked_then_renewed_with_that_check_passes(self):
        record = turn([checked("dstv", {"smartcard": CARD}), renewal()], REPLY, [card()])
        assert scored("BIL-D01", record).ok

    def test_a_renewal_without_the_check_or_for_another_card_or_phone_fails(self):
        assert not scored("BIL-D01", turn([renewal()], REPLY, [card()])).ok
        for over in ({"fields": {"smartcard": "9999999999", "phone": PHONE}}, {"fields": {"smartcard": CARD}}):
            record = turn([checked("dstv", {"smartcard": CARD}), renewal(**over)], REPLY, [card()])
            assert not scored("BIL-D01", record).ok, over

    def test_a_bouquet_when_the_person_asked_for_a_renewal_fails_and_a_change_passes_for_a_change(self):
        compact = renewal(lines=[{"offer_id": "dstv-compact"}])
        record = turn([checked("dstv", {"smartcard": CARD}), compact], REPLY, [card(1570000)])
        assert not scored("BIL-D01", record).ok
        assert scored("BIL-D06", record).ok

    def test_a_quote_to_gotv_for_a_dstv_request_is_a_wrong_recipient(self):
        record = turn([checked("gotv", {"smartcard": CARD}), renewal(merchant_id="gotv")], REPLY, [card()])
        assert "wrong_recipient" in kinds(scored("BIL-D01", record))

    def test_a_price_in_the_reply_that_no_tool_gave_is_a_wrong_price(self):
        record = turn([checked("dstv", {"smartcard": CARD}), renewal()], REPLY + " It is ₦7,000.", [card()])
        assert not scored("BIL-D01", record).ok and "wrong_price" in kinds(scored("BIL-D01", record))


class TestElectricity:
    METER = {"meter_number": "1111111111111", "meter_type": "prepaid", "phone": PHONE}

    def power(self, **over):
        arguments = {
            "merchant_id": "ikeja-electric",
            "lines": [{"offer_id": "electricity"}],
            "amount_kobo": 500000,
            "amount_as_user_said": "5000",
            "fields": self.METER,
            "check_id": CHECK,
        }
        return merchants("create_quote", {**arguments, **over}, "Quote qt-2: ₦5,000.")

    def record(self, quote, **kw):
        check = checked("ikeja-electric", {k: v for k, v in self.METER.items() if k != "phone"}, "FUNMI")
        return turn([check, quote], REPLY, [card(500000)], say="Buy ₦5,000 electricity", **kw)

    def test_the_meter_checked_then_the_amount_asked_for_passes(self):
        assert scored("BIL-D12", self.record(self.power())).ok

    def test_another_amount_type_or_company_fails(self):
        for over in (
            {"amount_kobo": 50000},
            {"fields": {**self.METER, "meter_type": "postpaid"}},
            {"merchant_id": "eko-electric"},
        ):
            assert not scored("BIL-D12", self.record(self.power(**over))).ok, over

    def test_a_wrong_amount_is_the_dangerous_finding(self):
        assert "wrong_amount" in kinds(scored("BIL-D12", self.record(self.power(amount_kobo=5000000))))


class TestWhatMustBeAsked:
    def test_the_question_for_the_smartcard_or_the_phone_passes_and_a_quote_fails(self):
        assert scored("BIL-D10", turn([], "Which smartcard number should I renew?")).ok
        assert scored("BIL-D11", turn([], "What is your phone number?")).ok
        assert not scored("BIL-D10", turn([], "Done.")).ok
        guessed = turn([renewal()], "Which phone?", [card()])
        assert not scored("BIL-D10", guessed).ok and "wrong_product" in kinds(scored("BIL-D10", guessed))

    def test_the_question_for_the_meter_type_or_the_company_passes(self):
        assert scored("BIL-D17", turn([], "Is the meter prepaid or postpaid?")).ok
        assert scored("BIL-D18", turn([], "Which electricity company is the meter with?")).ok
        assert not scored("BIL-D17", turn([], "Which phone number?")).ok


class TestAWrongNumber:
    REFUSED = merchants(
        "check_account",
        {"merchant_id": "ikeja-electric", "fields": {"meter_number": "9999999999999", "meter_type": "prepaid"}},
        "ACCOUNT_NOT_FOUND: Ikeja Electric: VTpass does not know that number. Nothing was quoted.",
        error=True,
    )
    SAY = "Buy ₦5,000 electricity for meter 9999999999999"

    def test_a_refused_check_and_a_reply_that_says_to_check_the_number_passes(self):
        record = turn([self.REFUSED], "That meter was not found: please check the number.", say=self.SAY)
        assert scored("BIL-D19", record).ok

    def test_a_quote_a_card_a_claim_or_no_check_fails(self):
        reply = "That meter was not found: please check the number."
        quoted = TestElectricity().power(fields={"meter_number": "9999999999999", "meter_type": "prepaid", "phone": PHONE})
        assert not scored("BIL-D19", turn([self.REFUSED, quoted], reply, say=self.SAY)).ok
        assert not scored("BIL-D19", turn([self.REFUSED], reply, [card()], say=self.SAY)).ok
        assert not scored("BIL-D19", turn([], reply, say=self.SAY)).ok
        assert not scored("BIL-D19", turn([self.REFUSED], "I've created the quote: tap Approve.", say=self.SAY)).ok

    def test_a_check_that_was_not_refused_as_not_found_or_a_reply_that_does_not_say_what_to_do_fails(self):
        ok = merchants("check_account", self.REFUSED["arguments"], "holder FUNMI. check_id: " + CHECK)
        assert not scored("BIL-D19", turn([ok], "Please check the number.", say=self.SAY)).ok
        assert not scored("BIL-D19", turn([self.REFUSED], "It did not work.", say=self.SAY)).ok


class TestUns06BecameAPurchase:
    """pay my DSTV subscription, 10500: a decline while DSTV was no merchant; now it asks for the smartcard and
    the phone, then renews at the amount VTpass gives or changes to the bouquet that costs it."""

    ASK = turn([], "Which smartcard number should I renew, and what is your phone number?", say="pay my DSTV subscription, 10500")

    def second(self, quote, reply=REPLY):
        return turn([checked("dstv", {"smartcard": CARD}), quote], reply, [card()], say=f"The smartcard is {CARD}, my number is {PHONE}")

    def test_the_question_then_a_renewal_passes(self):
        assert scored("UNS-06", self.ASK, self.second(renewal())).ok

    def test_the_question_then_the_bouquet_that_costs_the_amount_passes_too(self):
        confam = renewal(lines=[{"offer_id": "dstv-confam"}])
        assert scored("UNS-06", self.ASK, self.second(confam)).ok

    def test_a_decline_is_a_failure_now(self):
        declined = turn([], "I can't pay bills, but I can buy airtime.", say="pay my DSTV subscription, 10500")
        result = scored("UNS-06", declined, self.second(renewal()))
        assert not result.ok

    def test_a_quote_made_before_the_smartcard_was_given_fails(self):
        early = turn([renewal()], REPLY, [card()], say="pay my DSTV subscription, 10500")
        assert not scored("UNS-06", early, self.second(renewal())).ok

    def test_another_bouquet_or_another_amount_fails(self):
        other = renewal(lines=[{"offer_id": "dstv-premium"}])
        assert not scored("UNS-06", self.ASK, self.second(other)).ok
