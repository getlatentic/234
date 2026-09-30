# SPDX-License-Identifier: AGPL-3.0-or-later
"""Which network a number started on, and which numbers the connector accepts at all."""

import pytest

from checkout.errors import DomainError
from checkout.network import NETWORK_PREFIXES, network_of_number
from checkout.vtpass.phone import is_nigerian_mobile, normalise_phone


@pytest.mark.parametrize(
    ("number", "network"),
    [
        ("07031234567", "mtn"),
        ("07025000000", "mtn"),
        ("08031234567", "mtn"),
        ("09161234567", "mtn"),
        ("08021234567", "airtel"),
        ("09111234567", "airtel"),
        ("08051234567", "glo"),
        ("09151234567", "glo"),
        ("08091234567", "9mobile"),
        ("09081234567", "9mobile"),
        ("07021234567", None),
        ("07027000000", None),
        ("08011111111", None),
        ("201000000000", None),
    ],
)
def test_names_the_network_a_number_was_allocated_to(number, network):
    assert network_of_number(number) == network


def test_no_prefix_belongs_to_two_networks():
    seen: dict[str, str] = {}
    for network, prefixes in NETWORK_PREFIXES.items():
        for prefix in prefixes:
            assert seen.setdefault(prefix, network) == network
    every = [p for prefixes in NETWORK_PREFIXES.values() for p in prefixes]
    assert not any(a != b and a.startswith(b) for a in every for b in every)


@pytest.mark.parametrize(
    "text",
    ["0703 123 4567", "+234 703 123 4567", "234-703-123-4567", "(0703) 123 4567", "07031234567"],
)
def test_reads_the_same_number_however_it_is_typed(text):
    assert normalise_phone(text) == "07031234567"


@pytest.mark.parametrize(
    "text", ["", "703 123 4567", "0603 123 4567", "0703 123 456", "+1 415 555 0100", "abc"]
)
def test_refuses_what_is_not_a_nigerian_mobile_number(text):
    with pytest.raises(DomainError):
        normalise_phone(text)
    assert not is_nigerian_mobile(text)


@pytest.mark.parametrize(
    "number", ["201000000000", "500000000000", "400000000000", "300000000000", "100000000000"]
)
def test_keeps_the_scenario_numbers(number):
    assert normalise_phone(number) == number
