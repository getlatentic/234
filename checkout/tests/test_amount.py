# SPDX-License-Identifier: AGPL-3.0-or-later
"""Amount phrases, ported from the TypeScript demo's parse.test.ts, plus Pidgin spellings."""

import pytest

from checkout.amount.parse import parse_naira_amount


def naira(n: int) -> int:
    return n * 100


ACCEPTED = [
    ("5k", naira(5_000)),
    ("5K", naira(5_000)),
    ("5 k", naira(5_000)),
    ("₦25,000", naira(25_000)),
    ("N25,000", naira(25_000)),
    ("n25000", naira(25_000)),
    ("NGN 25000", naira(25_000)),
    ("25,000 naira", naira(25_000)),
    ("₦500", naira(500)),
    ("500", naira(500)),
    ("2.5k naira", naira(2_500)),
    ("₦2.5k", naira(2_500)),
    ("1.5m", naira(1_500_000)),
    ("1 million", naira(1_000_000)),
    ("5 thousand", naira(5_000)),
    ("5 hundred", naira(500)),
    ("₦25,000.50", 2_500_050),
    ("₦0.50", 50),
    ("50 kobo", 50),
    ("two thousand", naira(2_000)),
    ("Two Thousand Naira", naira(2_000)),
    ("two thousand five hundred", naira(2_500)),
    ("two thousand and five hundred naira", naira(2_500)),
    ("twenty five thousand", naira(25_000)),
    ("twenty-five thousand naira", naira(25_000)),
    ("five", naira(5)),
    ("five hundred", naira(500)),
    ("five hundred naira only", naira(500)),
    ("a hundred", naira(100)),
    ("hundred naira", naira(100)),
    ("fifteen hundred", naira(1_500)),
    ("twenty five hundred", naira(2_500)),
    ("two hundred and fifty thousand", naira(250_000)),
    ("one million two hundred thousand", naira(1_200_000)),
    ("a thousand", naira(1_000)),
    ("five k", naira(5_000)),
    ("two grand", naira(2_000)),
    ("  ₦ 1,000  ", naira(1_000)),
]

PIDGIN = [
    ("wan tousand", naira(1_000)),
    ("tu tousand naira", naira(2_000)),
    ("fiv hundrid", naira(500)),
    ("wan k", naira(1_000)),
    ("ten tousand naira", naira(10_000)),
    ("tu tousand fayv hondred", naira(2_500)),
    ("wan milion", naira(1_000_000)),
    ("fifty naira", naira(50)),
    ("five hundred naira only", naira(500)),
]

REFUSED = [
    ("", "empty"),
    ("   ", "empty"),
    ("naira", "empty"),
    ("5k or 10k", "ambiguous"),
    ("500 or 5000", "ambiguous"),
    ("500 to 1000", "ambiguous"),
    ("5k-10k", "ambiguous"),
    ("between 2k and 3k", "ambiguous"),
    ("about 5k", "ambiguous"),
    ("around five thousand", "ambiguous"),
    ("500 1000", "ambiguous"),
    ("5,00", "ambiguous"),
    ("1,5k", "ambiguous"),
    ("25,00,000", "ambiguous"),
    ("2.500", "ambiguous"),
    ("$50", "wrong_currency"),
    ("50 dollars", "wrong_currency"),
    ("£20", "wrong_currency"),
    ("0", "not_positive"),
    ("₦0", "not_positive"),
    ("₦2.555", "ambiguous"),
    ("₦2.5555", "too_precise"),
    ("0.000001k", "too_precise"),
    ("5kk", "unparseable"),
    ("two five hundred", "unparseable"),
    ("thousand thousand", "unparseable"),
    ("five thousand thousand", "unparseable"),
    ("five hundred thousand thousand", "unparseable"),
    ("give me money", "unparseable"),
    ("5k airtime", "unparseable"),
    ("five thousand million", "unparseable"),
    ("2000 million naira x", "unparseable"),
    ("2000 million", "too_large"),
    ("1.5 billion", "unparseable"),
    ("tu wan tousand", "unparseable"),
    ("wan tousand tousand", "unparseable"),
]


@pytest.mark.parametrize(("phrase", "kobo"), ACCEPTED + PIDGIN)
def test_reads_nigerian_phrasings(phrase, kobo):
    assert parse_naira_amount(phrase).kobo == kobo


@pytest.mark.parametrize(("phrase", "reason"), REFUSED)
def test_refuses_instead_of_guessing(phrase, reason):
    result = parse_naira_amount(phrase)
    assert (result.kobo, result.reason) == (None, reason)


def test_explains_a_rejection_in_words_the_model_can_act_on():
    assert "range or an estimate" in parse_naira_amount("5k or 10k").message


@pytest.mark.parametrize("phrase", ["5 constructor", "constructor", "5 __class__", "__class__"])
def test_does_not_treat_object_attributes_as_unit_words(phrase):
    assert parse_naira_amount(phrase).kobo is None


def test_a_number_word_never_reads_as_a_different_amount():
    """Every English or Pidgin spelling of a small number reads as that number, or is refused."""
    for word, value in (("wan", 1), ("tu", 2), ("tri", 3), ("fiv", 5), ("eit", 8), ("nain", 9)):
        assert parse_naira_amount(word).kobo == naira(value)
