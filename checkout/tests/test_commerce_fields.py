# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the buyer gives a merchant, read against the fields it asks for."""

import pytest

from checkout.commerce.fields import MAX_FIELDS, buyer_fields
from checkout.commerce.model import FieldSpec, Merchant
from checkout.errors import DomainError

SPECS = (
    FieldSpec("area", "Delivery area", "choice", True, ("Yaba", "Ikeja GRA")),
    FieldSpec("number", "Customer number", "digits", True, least=8, most=10),
    FieldSpec("note", "Note", "text", False, most=20),
)
MERCHANT = Merchant("m", "directory", "Shop", "shop", "live", False, "b", 1, 2, "Fee", 0, False, SPECS)
GOOD = {"area": "yaba", "number": "1001 2345", "note": "  by   the gate "}


def code(given) -> str:
    with pytest.raises(DomainError) as refused:
        buyer_fields(MERCHANT, given)
    return refused.value.code


def test_fields_are_read_in_the_merchants_order_cleaned_and_spelled_as_the_merchant_does():
    assert buyer_fields(MERCHANT, GOOD) == (
        ("area", "Delivery area", "Yaba"),
        ("number", "Customer number", "10012345"),
        ("note", "Note", "by the gate"),
    )


def test_an_optional_field_may_be_left_out():
    read = buyer_fields(MERCHANT, {"area": "Yaba", "number": "10012345"})
    assert [name for name, _, _ in read] == ["area", "number"]


def test_a_field_the_merchant_does_not_ask_for_is_refused_and_not_kept():
    assert code({**GOOD, "price": "1"}) == "FIELD_INVALID"


def test_a_required_field_missing_or_blank_is_refused():
    assert code({"number": "10012345"}) == "FIELD_REQUIRED"
    assert code({**GOOD, "area": "  "}) == "FIELD_REQUIRED"


@pytest.mark.parametrize("area", ["Lagos Island", "Yaba, Ikeja GRA"])
def test_a_choice_must_be_one_of_the_options(area):
    assert code({**GOOD, "area": area}) == "FIELD_INVALID"


@pytest.mark.parametrize("number", ["1234567", "12345678901", "10012345a", "ten"])
def test_digits_must_be_digits_within_their_length(number):
    assert code({**GOOD, "number": number}) == "FIELD_INVALID"


def test_text_is_limited_and_has_no_control_characters():
    assert code({**GOOD, "note": "x" * 21}) == "FIELD_INVALID"
    assert buyer_fields(MERCHANT, {**GOOD, "note": "a\nb\x00"})[2][2] == "a b"


def test_no_more_than_the_most_fields():
    assert code({f"f{i}": "x" for i in range(MAX_FIELDS + 1)}) == "FIELD_INVALID"
