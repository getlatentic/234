# SPDX-License-Identifier: AGPL-3.0-or-later
import pytest

from turns.inputs import InputRefused, clean_text, contains_card_number


def refusal(value):
    with pytest.raises(InputRefused) as caught:
        clean_text(value)
    return caught.value.code


def test_text_is_trimmed():
    assert clean_text("  pay ₦2,500 to Demo Kitchen ") == "pay ₦2,500 to Demo Kitchen"


def test_empty_and_oversized_messages_are_refused():
    assert refusal("   ") == "empty"
    assert refusal(None) == "empty"
    assert refusal("x" * 501) == "too_long"
    assert clean_text("x" * 500)


@pytest.mark.parametrize("number", ["4242 4242 4242 4242", "4111-1111-1111-1111", "378282246310005"])
def test_card_numbers_are_refused_however_they_are_written(number):
    assert refusal(f"pay with {number} please") == "card_data"


@pytest.mark.parametrize(
    "text", ["call 08012345678", "ref 1234567890123456", "order 2026092911223344", "pay ₦4,242"]
)
def test_long_numbers_that_are_not_cards_pass(text):
    assert not contains_card_number(text)
