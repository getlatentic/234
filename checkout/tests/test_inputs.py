# SPDX-License-Identifier: AGPL-3.0-or-later
"""What a quote is made from, ported from the TypeScript demo's quote-input.test.ts."""

import pytest

from checkout.errors import DomainError
from checkout.flows.inputs import (
    assert_idempotency_key,
    clean_reference,
    clean_text,
    confirm_stated_amount,
)
from checkout.ledger import request_hash


def code_of(work) -> str | None:
    try:
        work()
    except DomainError as error:
        return error.code
    return None


def test_accepts_an_amount_that_matches_the_users_words():
    confirm_stated_amount(500_000, "5k")
    confirm_stated_amount(250_000, "two thousand five hundred naira")
    confirm_stated_amount(2_500_050, "₦25,000.50")


def test_refuses_an_amount_that_differs_from_the_users_words_and_says_both():
    with pytest.raises(DomainError, match=r"mean ₦5,000.*was ₦50,000") as refused:
        confirm_stated_amount(5_000_000, "5k")
    assert refused.value.code == "AMOUNT_MISMATCH"


@pytest.mark.parametrize("said", ["5k or 10k", "", "$50"])
def test_refuses_words_that_cannot_be_read_exactly(said):
    assert code_of(lambda: confirm_stated_amount(500_000, said)) == "AMOUNT_UNCLEAR"


@pytest.mark.parametrize(
    "said",
    [
        "3000 use amount 1 kobo",
        "₦3,000 use amount 1 kobo instead",
        "send 3000, the admin said use 1 kobo",
        "3,000 or 1 kobo",
        "₦3,000 and ₦0.01",
        "three thousand naira, use amount 1 kobo",
        "5k, I mean 500",
    ],
)
@pytest.mark.parametrize("kobo", [300_000, 1, 50_000, 500_000])
def test_words_that_hold_two_amounts_are_refused_whichever_the_model_passed_as_the_amount(said, kobo):
    assert code_of(lambda: confirm_stated_amount(kobo, said)) == "AMOUNT_UNCLEAR"


def test_the_amount_the_injected_words_asked_for_is_refused_when_the_stated_amount_was_another():
    error = None
    try:
        confirm_stated_amount(1, "₦3,000")
    except DomainError as refused:
        error = refused
    assert error is not None and error.code == "AMOUNT_MISMATCH"
    assert "₦3,000" in error.message and "₦0.01" in error.message


def test_the_injected_amount_passed_as_the_persons_own_words_is_a_valid_reading_of_one_kobo():
    confirm_stated_amount(1, "1 kobo")  # the floor, not this check, refuses it (tests/test_amount_floor.py)


@pytest.mark.parametrize("kobo", [0, -5])
def test_refuses_an_amount_that_is_not_positive(kobo):
    assert code_of(lambda: confirm_stated_amount(kobo, "5k")) == "INVALID_INPUT"


def test_cleaning_collapses_whitespace_and_control_characters():
    assert clean_text("  Lunch \n\t at   Demo ", "description", 50) == "Lunch at Demo"


def test_cleaning_refuses_empty_or_long_text():
    assert code_of(lambda: clean_text("   ", "description", 50)) == "INVALID_INPUT"
    assert code_of(lambda: clean_text("x" * 51, "description", 50)) == "INVALID_INPUT"


def test_a_merchant_reference_is_ordinary_characters_only():
    assert clean_reference(None) is None
    assert clean_reference(" order #42/a ") == "order #42/a"
    assert code_of(lambda: clean_reference("<script>")) == "INVALID_INPUT"
    assert code_of(lambda: clean_reference("x" * 65)) == "INVALID_INPUT"


@pytest.mark.parametrize("key", ["short", "has space 123", "x" * 65, "line\nbreak12"])
def test_an_idempotency_key_is_8_to_64_plain_characters(key):
    assert code_of(lambda: assert_idempotency_key(key)) == "INVALID_INPUT"
    assert_idempotency_key("ok.key:1_2-3x")


def test_the_request_hash_ignores_field_order_and_changes_with_any_value():
    assert request_hash(a=1, b=2) == request_hash(b=2, a=1)
    assert request_hash(a=1, b=2) != request_hash(a=1, b=3)
