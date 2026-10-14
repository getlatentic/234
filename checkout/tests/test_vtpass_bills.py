# SPDX-License-Identifier: AGPL-3.0-or-later
"""What VTpass says about television and electricity, read (vtpass/bills.py, vtpass/receipt.py,
vtpass/interpret.py): an account check that refuses a wrong number, bouquets, the request that is sent and
what a delivered bill gives the buyer. The documentation's samples lack what its prose promises, so every
field but the holder is optional."""

import pytest

from checkout.vtpass.api import VtpassError
from checkout.vtpass.bills import (
    SERVICES,
    BillOrder,
    BillRefused,
    account_from,
    bouquets_from,
    kobo_of,
    pay_body,
)
from checkout.vtpass.interpret import interpret_vtpass
from checkout.vtpass.receipt import bill_receipt


def verified(**content):
    return {"code": "000", "content": {"Customer_Name": "TEST METER", **content}}


class TestNaira:
    @pytest.mark.parametrize(
        ("written", "kobo"),
        [("1850.00", 185_000), (500, 50_000), (12041.38, 1_204_138), ("1,000", 100_000), ("0.5", 50)],
    )
    def test_is_read_in_kobo(self, written, kobo):
        assert kobo_of(written) == kobo

    @pytest.mark.parametrize("written", ["", None, "abc", True, "-5", "nan", "inf", [1]])
    def test_is_none_when_there_is_none(self, written):
        assert kobo_of(written) is None


class TestAnAccountCheck:
    def test_reads_the_documented_television_sample_without_a_bouquet_or_a_renewal_amount(self):
        found = account_from(
            verified(Status="ACTIVE", Due_Date="2025-02-06T00:00:00", Customer_Number="8061522780")
        )
        assert (found.holder, found.status, found.due_date) == ("TEST METER", "ACTIVE", "2025-02-06T00:00:00")
        assert found.bouquet is None and found.renewal_kobo is None

    def test_reads_the_bouquet_and_the_renewal_amount_when_they_are_given(self):
        found = account_from(verified(Current_Bouquet="DStv Compact", Renewal_Amount=15700))
        assert (found.bouquet, found.renewal_kobo) == ("DStv Compact", 1_570_000)

    def test_reads_a_meter_with_its_limits_and_leaves_an_empty_one_out(self):
        found = account_from(
            verified(
                Address="1 Allen Avenue",
                Customer_Arrears="8350.50",
                Minimum_Amount="",
                Min_Purchase_Amount="1000",
                MAX_Purchase_Amount="500000",
                Can_Vend="true",
                Meter_Type="PREPAID",
            )
        )
        assert (found.address, found.arrears_kobo) == ("1 Allen Avenue", 835_050)
        assert (found.min_kobo, found.max_kobo, found.meter_type) == (100_000, 50_000_000, "PREPAID")

    def test_takes_the_least_from_either_of_the_two_fields_it_may_come_in(self):
        assert account_from(verified(Minimum_Amount="12041.38")).min_kobo == 1_204_138
        assert account_from(verified(Minimum_Amount="", Min_Purchase_Amount="500")).min_kobo == 50_000

    def test_states_no_maximum_when_vtpass_gives_none(self):
        assert account_from(verified(Min_Purchase_Amount="500")).max_kobo is None

    @pytest.mark.parametrize("wrong", [True, "true", "True"])
    def test_a_wrong_number_is_refused(self, wrong):
        with pytest.raises(BillRefused):
            account_from(verified(WrongBillersCode=wrong))

    def test_a_number_that_vtpass_could_not_verify_is_refused(self):
        with pytest.raises(BillRefused):
            account_from(verified(error="Unable to verify"))

    @pytest.mark.parametrize("can_vend", ["false", "False", "NO", "0", False])
    def test_a_meter_vtpass_cannot_sell_to_is_refused(self, can_vend):
        with pytest.raises(BillRefused, match="cannot be sold to"):
            account_from(verified(Can_Vend=can_vend))

    def test_a_meter_that_can_be_sold_to_is_not_refused(self):
        assert account_from(verified(Can_Vend="true", WrongBillersCode=False)).holder == "TEST METER"

    @pytest.mark.parametrize(
        "reply",
        [None, "text", [], {}, {"code": "000"}, {"content": None}, {"content": {"Customer_Name": ""}}],
    )
    def test_a_reply_without_a_holder_is_refused(self, reply):
        with pytest.raises(BillRefused):
            account_from(reply)


class TestBouquets:
    def test_are_the_fixed_price_variations_in_kobo(self):
        found = bouquets_from(
            {
                "content": {
                    "variations": [
                        {"variation_code": "dstv-padi", "name": "DStv Padi", "variation_amount": "4400.00"},
                        {
                            "variation_code": "open",
                            "name": "Any",
                            "variation_amount": "0",
                            "fixedPrice": "No",
                        },
                    ],
                    "varations": [{"variation_code": "ignored", "name": "x", "variation_amount": "1"}],
                }
            }
        )
        assert [(b.code, b.name, b.amount_kobo) for b in found] == [("dstv-padi", "DStv Padi", 440_000)]

    @pytest.mark.parametrize("reply", [None, {}, {"content": {}}, {"content": {"variations": "x"}}])
    def test_a_reply_without_a_list_is_an_error(self, reply):
        with pytest.raises(VtpassError):
            bouquets_from(reply)

    def test_a_list_with_nothing_to_buy_is_an_error(self):
        with pytest.raises(VtpassError, match="no bouquets"):
            bouquets_from({"content": {"variations": [{"variation_code": "x", "name": "y"}]}})


class TestThePayRequest:
    def order(self, **over):
        return BillOrder(
            **{"request_id": "r1", "service_id": "ikeja-electric", "billers_code": "1", "phone": "0803"}
            | {"amount_kobo": 500_000}
            | over
        )

    def test_a_meters_type_rides_as_the_variation_code_and_the_amount_is_in_naira(self):
        body = pay_body(self.order(meter_type="postpaid"))
        assert body == {
            "request_id": "r1",
            "serviceID": "ikeja-electric",
            "billersCode": "1",
            "amount": 5000,
            "phone": "0803",
            "variation_code": "postpaid",
        }

    def test_a_renewal_names_no_bouquet_and_says_for_how_long(self):
        body = pay_body(self.order(service_id="dstv", subscription_type="renew", quantity=1))
        assert "variation_code" not in body
        assert (body["subscription_type"], body["quantity"]) == ("renew", 1)

    def test_a_bouquet_change_names_the_bouquet(self):
        body = pay_body(self.order(service_id="gotv", variation_code="gotv-max", subscription_type="change"))
        assert (body["variation_code"], body["subscription_type"]) == ("gotv-max", "change")

    def test_an_amount_with_kobo_is_sent_as_a_decimal(self):
        assert pay_body(self.order(amount_kobo=1_204_138))["amount"] == 12041.38


class TestWhatADeliveredBillGives:
    def test_a_prepaid_reply_gives_the_token_in_groups_with_its_units_and_tariff(self):
        got = bill_receipt(
            {
                "token": "Token : 26362054405982757802",
                "units": "79.9 kWh",
                "tariff": "R2",
                "purchased_code": "",
            }
        )
        assert got == (("Token", "2636 2054 4059 8275 7802"), ("Units", "79.9 kWh"), ("Tariff", "R2"))

    def test_the_token_is_found_in_the_purchased_code_when_the_reply_has_no_token_field(self):
        assert bill_receipt({"purchased_code": "Token : 1234567890"}) == (("Token", "1234 5678 90"),)

    def test_a_bare_token_is_taken_as_it_is(self):
        assert bill_receipt({"token": "12345678"}) == (("Token", "1234 5678"),)

    def test_a_postpaid_reply_has_no_token(self):
        assert bill_receipt({"purchased_code": "", "customerName": "X", "balance": 0}) == ()

    def test_a_purchased_code_that_is_not_a_token_is_not_shown_as_one(self):
        assert bill_receipt({"purchased_code": "SOMETHING-ELSE"}) == ()

    def test_a_showmax_voucher_is_shown(self):
        assert bill_receipt({"Voucher": " SMX-1 "}) == (("Voucher", "SMX-1"),)


class TestAReplyReadAsAnOrdersOutcome:
    def reply(self, status="delivered", code="000", **top):
        return {
            "code": code,
            "response_description": "TRANSACTION SUCCESSFUL",
            "content": {"transactions": {"status": status}},
            **top,
        }

    def test_a_delivered_prepaid_order_carries_its_token(self):
        outcome = interpret_vtpass(self.reply(token="Token : 1234", units="5 kWh"))
        assert outcome.status == "delivered" and dict(outcome.receipt) == {"Token": "1234", "Units": "5 kWh"}

    def test_a_pending_order_carries_nothing_and_is_never_failed(self):
        outcome = interpret_vtpass(self.reply("pending", token="Token : 1234"))
        assert (outcome.status, outcome.receipt) == ("pending", ())

    def test_a_reversal_is_a_failure_marked_as_one(self):
        outcome = interpret_vtpass(self.reply("reversed", "040"))
        assert (outcome.status, outcome.reversed, outcome.receipt) == ("failed", True, ())


def test_every_service_is_a_television_service_or_one_of_the_twelve_distribution_companies():
    kinds = [kind for kind, _ in SERVICES.values()]
    assert kinds.count("tv") == 4 and kinds.count("electricity") == 12
    assert {"dstv", "gotv", "startimes", "showmax", "ikeja-electric", "portharcourt-electric"} <= set(
        SERVICES
    )
