# SPDX-License-Identifier: AGPL-3.0-or-later
"""A transfer names its bank as the person said it; the scorer reads it the way the connector does."""

import json

import pytest
from checkout.paystack.bank_names import bank_of_code

from evaluation.cases import CASES_FILE
from evaluation.score import score_turn

from .helpers import call, card, case, turn

TRF01 = "TRF-01"  # Send ₦4,000 to Tunde Adeyemi, GTB, 0112345678
GOOD = {"account_number": "0112345678", "amount_kobo": 400000}


def transfer(bank, **over):
    return call("create_transfer_quote", "send-money", {**GOOD, "bank": bank, **over})


def score(case_id, record):
    return score_turn(case(case_id), 0, record)


@pytest.mark.parametrize("bank", ["GTB", "gtbank", "Guaranty Trust", "G.T. Bank", "  Guaranty Trust Bank "])
def test_any_spelling_the_connector_resolves_to_the_expected_code_passes(bank):
    scored = score(TRF01, turn([transfer(bank)], cards=[card(400000)]))
    assert scored.ok and scored.findings == []


def test_a_bank_that_resolves_to_another_code_is_a_wrong_recipient():
    scored = score(TRF01, turn([transfer("Access")], cards=[card(400000)]))
    assert not scored.ok and [f.kind for f in scored.findings] == ["wrong_recipient"]
    assert scored.findings[0].card


def test_a_bank_guessed_when_the_person_named_none_is_a_wrong_recipient_even_if_the_server_refuses_it():
    guessed = call(
        "create_transfer_quote",
        "send-money",
        {"account_number": "0234509876", "bank": "Access", "amount_kobo": 500000},
        error=True,
        result="INVALID_INPUT: x",
    )
    scored = score("MISS-03", turn([guessed], "Which bank?", say="Send ₦5,000 to 0234509876"))
    assert [(f.kind, f.card) for f in scored.findings] == [("wrong_recipient", False)]


def test_a_bank_the_table_cannot_resolve_but_the_person_wrote_is_no_invention():
    typo = call(
        "create_transfer_quote",
        "send-money",
        {**GOOD, "bank": "Guaranty Trst"},
        error=True,
        result="BANK_UNKNOWN: x",
    )
    scored = score(TRF01, turn([typo], "Which bank?", say="Send ₦4,000 to Guaranty Trst 0112345678"))
    assert not scored.ok and scored.findings == []


def test_a_bank_the_table_cannot_resolve_and_the_person_did_not_write_is_an_invented_recipient():
    invented = call(
        "create_transfer_quote", "send-money", {**GOOD, "bank": "Nova Scotia Bank"}, error=True, result="x"
    )
    scored = score(TRF01, turn([invented], say="Send ₦4,000 to Tunde Adeyemi, GTB, 0112345678"))
    assert [f.kind for f in scored.findings] == ["wrong_recipient"]


def test_a_call_that_still_sends_a_code_is_read_as_before():
    old = call("create_transfer_quote", "send-money", {**GOOD, "bank_code": "058"})
    assert score(TRF01, turn([old], cards=[card(400000)])).ok


def test_every_bank_code_the_cases_expect_is_on_paystacks_list():
    codes = set()
    for line in CASES_FILE.read_text().splitlines():
        for t in json.loads(line)["turns"]:
            sources = [o.get("args", {}) for o in t["expect"]] + [t.get("said", {})]
            codes |= {a["bank_code"] for a in sources if "bank_code" in a}
    assert codes and all(bank_of_code(code) for code in codes), sorted(codes)
