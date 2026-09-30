# SPDX-License-Identifier: AGPL-3.0-or-later
"""The scripted model follows the host's prompt for the starters: it asks for what is missing, calls the
connector's tool when it has everything, describes itself from its tools, and refuses the rest."""

from . import scripted_intents as intents

TOOLS = [
    {"type": "function", "function": {"name": name}}
    for name in (
        "airtime__create_airtime_quote",
        "airtime__create_data_quote",
        "send-money__create_transfer_quote",
        "food-order__search_menu",
        "paystack-pay__create_payment_quote",
    )
]


def say(*texts, tools=TOOLS):
    messages = [{"role": "user", "content": t} for t in texts]
    return intents.answer(messages, tools)


def test_what_can_you_do_is_built_from_the_tools_it_was_offered():
    text = say("What can you do?")["text"]
    assert text == (
        "I can buy airtime, buy data, send money to a bank account, order food and pay a merchant. "
        "You approve every payment on a card."
    )
    assert "order food" not in say("What can you do?", tools=TOOLS[:1])["text"]


def test_airtime_asks_for_the_number_then_quotes_it():
    assert say("Buy ₦500 MTN airtime")["text"] == "Which number should get the ₦500 MTN airtime?"
    call = say("Buy ₦500 MTN airtime", "08031234567")
    assert call["tool"] == "airtime__create_airtime_quote"
    assert call["arguments"]["amount_kobo"] == 50000 and call["arguments"]["network"] == "mtn"
    assert call["arguments"]["phone"] == "08031234567"


def test_data_asks_for_the_number_lists_the_plans_and_quotes_the_one_at_that_price():
    assert say("Buy ₦1,000 MTN data")["text"] == "Which number should get the ₦1,000 MTN data?"
    assert say("Buy ₦1,000 MTN data", "08031234567")["tool"] == "airtime__list_data_plans"
    messages = [
        {"role": "user", "content": "Buy ₦1,000 MTN data"},
        {"role": "user", "content": "08031234567"},
        {
            "role": "tool",
            "content": (
                "MTN data plans:\nmtn-10mb-100: N100 100MB, ₦100.00\nmtn-100mb-1000: N1000 1.5GB, ₦1,000.00"
            ),
        },
    ]
    call = intents.answer(messages, TOOLS)
    assert call["tool"] == "airtime__create_data_quote" and call["arguments"]["plan_code"] == "mtn-100mb-1000"


def test_a_transfer_asks_for_the_account_and_bank_then_quotes_it():
    assert "account number and bank" in say("Send ₦5,000 to a friend")["text"]
    call = say("Send ₦5,000 to a friend", "0000000000 Zenith")
    assert call["tool"] == "send-money__create_transfer_quote"
    assert call["arguments"]["bank"] == "Zenith" and call["arguments"]["amount_kobo"] == 500000


def test_food_searches_the_menu_for_what_was_asked():
    call = say("Order jollof rice for delivery")
    assert call == {"tool": "food-order__search_menu", "arguments": {"query": "jollof rice"}}


def test_anything_else_is_turned_down_naming_what_it_can_do():
    assert intents.refusal(TOOLS).startswith("I can't do that. I can buy airtime")
    assert intents.refusal([]) == "I can't do that."


def test_a_number_with_nothing_before_it_is_not_taken_for_a_request():
    assert say("08031234567") is None


def test_a_starter_finished_by_the_person_is_answered_in_one_step():
    airtime = say("Buy ₦500 MTN airtime for 08031234567")
    assert (
        airtime["tool"] == "airtime__create_airtime_quote" and airtime["arguments"]["phone"] == "08031234567"
    )
    assert say("Buy ₦1,000 MTN data for 08031234567") == {
        "tool": "airtime__list_data_plans",
        "arguments": {"network": "mtn"},
    }
    transfer = say("Send ₦5,000 to 0000000000 Zenith")
    assert transfer["tool"] == "send-money__create_transfer_quote"
    assert (
        transfer["arguments"]["account_number"] == "0000000000" and transfer["arguments"]["bank"] == "Zenith"
    )


def test_a_data_request_that_names_its_number_is_quoted_from_the_plan_list():
    messages = [
        {"role": "user", "content": "Buy ₦1,000 MTN data for 08031234567"},
        {"role": "tool", "content": "MTN data plans:\nmtn-100mb-1000: N1000 1.5GB, ₦1,000.00"},
    ]
    call = intents.answer(messages, TOOLS)
    assert call["tool"] == "airtime__create_data_quote" and call["arguments"]["phone"] == "08031234567"


REFUSAL = {"role": "tool", "content": "Invalid arguments for create_airtime_quote: phone: too short"}


def test_the_blank_phone_request_calls_the_tool_with_an_empty_number():
    call = say("blank phone: Buy ₦500 MTN airtime")
    assert call["tool"] == "airtime__create_airtime_quote" and call["arguments"]["phone"] == ""
    assert call["arguments"]["amount_kobo"] == 50000


def test_after_the_refusal_it_asks_for_the_number_or_uses_the_one_it_was_given_or_says_nothing():
    asked = intents.answer([{"role": "user", "content": "blank phone: Buy ₦500 MTN airtime"}, REFUSAL], TOOLS)
    assert asked == {"text": "Which number should get the ₦500 MTN airtime?"}
    again = intents.answer(
        [{"role": "user", "content": "blank phone: Buy ₦500 MTN airtime for 08031234567"}, REFUSAL], TOOLS
    )
    assert again["tool"] == "airtime__create_airtime_quote" and again["arguments"]["phone"] == "08031234567"
    silent = intents.answer(
        [{"role": "user", "content": "blank phone, silent: Buy ₦500 MTN airtime"}, REFUSAL], TOOLS
    )
    assert silent == {"text": ""}


def test_a_refusal_that_no_blank_phone_request_caused_is_not_answered():
    assert intents.answer([{"role": "user", "content": "Buy ₦500 MTN airtime"}, REFUSAL], TOOLS) is None
