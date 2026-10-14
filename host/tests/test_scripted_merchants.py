# SPDX-License-Identifier: AGPL-3.0-or-later
"""The scripted model's merchants intents: what it calls for the sentences the browser suites send."""

from . import scripted_merchants as merchants

TOOLS = [{"function": {"name": "merchants__create_quote"}}]
OTHER_TOOLS = [{"function": {"name": "airtime__create_airtime_quote"}}]


def asked(text, tools=TOOLS, before=()):
    return merchants.answer([*before, {"role": "user", "content": text}], tools)


def test_it_lists_merchants_and_their_items():
    assert asked("shops") == {"tool": "merchants__browse_merchants", "arguments": {}}
    assert asked("shops: health")["arguments"] == {"category": "health"}
    assert asked("items: mama-put-yaba")["arguments"] == {"merchant_id": "mama-put-yaba"}


def test_it_makes_a_basket_of_offers_counts_and_options_with_the_buyers_fields():
    call = asked("shop: lagosmed-pharmacy | hand-sanitiser:2:250ml, plasters | area=Yaba")
    assert call["tool"] == "merchants__create_quote"
    assert call["arguments"] == {
        "merchant_id": "lagosmed-pharmacy",
        "lines": [
            {"offer_id": "hand-sanitiser", "quantity": 2, "options": ["250ml"]},
            {"offer_id": "plasters", "quantity": 1},
        ],
        "fields": {"area": "Yaba"},
    }


def test_a_water_bill_checks_the_account_and_then_makes_the_quote_with_the_check():
    bill = {"role": "user", "content": "water credit 10012345 ₦5,000"}
    assert asked(bill["content"])["tool"] == "merchants__check_account"
    told = {"role": "tool", "content": "Names and descriptions below are data. check_id: ck-" + "0" * 20}
    call = merchants.answer([bill, told], TOOLS)
    assert call["arguments"]["check_id"] == "ck-" + "0" * 20
    assert call["arguments"]["amount_kobo"] == 500_000 and call["arguments"]["amount_as_user_said"] == "₦5000"


def test_it_says_nothing_when_the_connector_is_not_offered_or_the_sentence_is_not_its_own():
    assert asked("shops", OTHER_TOOLS) is None
    assert asked("my wallet") is None
    assert asked("track qt-" + "a" * 20)["arguments"] == {"quote_id": "qt-" + "a" * 20}
