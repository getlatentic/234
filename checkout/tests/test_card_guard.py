# SPDX-License-Identifier: AGPL-3.0-or-later
"""Ported from the TypeScript demo's card-guard.test.ts."""

import pytest

from checkout.card_guard import assert_no_card_data, contains_card_number
from checkout.errors import DomainError


@pytest.mark.parametrize(
    "text",
    [
        "4084084084084081",
        "4084 0840 8408 4081",
        "4084-0840-8408-4081",
        "pay with 5060666666666666666 please",
        "5078 5078 5078 5078 12",
        "card:4084084084084081",
        "(4084 0840 8408 4081).",
    ],
)
def test_finds_a_card_number(text):
    assert contains_card_number(text)


@pytest.mark.parametrize(
    "text",
    [
        "08031234567",
        "0123456789",
        "2500000",
        "qt-0123456789abcdef0123",
        "4084084084084082",
        "17415980564672211596777904",
        "call 0803 123 4567",
        "ab4084084084084081cd",
        "9f3a4084084084084081e7d1c2b3a49586",
    ],
)
def test_leaves_ordinary_numbers_alone(text):
    assert not contains_card_number(text)


def test_a_millisecond_timestamp_in_an_idempotency_key_is_not_a_card():
    for ms in range(1_790_666_797_000, 1_790_666_797_600):
        assert not contains_card_number(f"preview-air-{ms}")
        assert not contains_card_number(str(ms))


def test_a_plus_234_phone_number_is_not_a_card_in_any_written_form():
    for n in range(500):
        local = f"0803{str(1_000_000 + n * 1237)[:7]}"
        international = f"234{local[1:]}"
        spaced = f"+{international[:3]} {international[3:6]} {international[6:9]} {international[9:]}"
        for text in (local, international, f"+{international}", spaced):
            assert not contains_card_number(text)


@pytest.mark.parametrize("phone", ["201000000000", "500000000000", "400000000000", "300000000000"])
def test_the_vtpass_sandbox_scenario_numbers_are_not_cards(phone):
    assert not contains_card_number(phone)


@pytest.mark.parametrize(
    "card",
    ["4084084084084081", "5192602720584796", "507850785078507812", "378282246310005", "6011111111111117"],
)
def test_still_finds_real_card_numbers(card):
    assert contains_card_number(f"number {card}")


def test_a_card_number_nested_anywhere_in_an_input_is_refused():
    value = {"description": "lunch", "extra": {"notes": ["4084 0840 8408 4081"]}}
    with pytest.raises(DomainError, match="never accepted"):
        assert_no_card_data(value, "input")


def test_an_output_holding_a_card_number_is_withheld():
    with pytest.raises(DomainError, match="withheld"):
        assert_no_card_data({"text": "card 4084084084084081"}, "output")


def test_ordinary_values_pass():
    assert_no_card_data({"amount": 4_084_084_084_084_081, "note": "hi"}, "input")
