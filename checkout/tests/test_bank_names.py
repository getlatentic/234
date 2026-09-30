# SPDX-License-Identifier: AGPL-3.0-or-later
"""The table that turns the bank a person named into Paystack's code. The expected names and codes below are
written by hand from Paystack's list (`GET /bank?country=nigeria`), not read from the table under test."""

import pytest

from checkout.paystack.bank_aliases import BANK_ALIASES
from checkout.paystack.bank_list import BANK_LIST
from checkout.paystack.bank_names import (
    MAX_CANDIDATES,
    BankAmbiguous,
    BankNotFound,
    bank_of_code,
    normalise,
    resolve_bank,
)

SPOKEN = [
    ("Access", "044", "Access Bank"),
    ("access bank", "044", "Access Bank"),
    ("Zenith", "057", "Zenith Bank"),
    ("Zenith Bank Plc", "057", "Zenith Bank"),
    ("GTB", "058", "Guaranty Trust Bank"),
    ("GTBank", "058", "Guaranty Trust Bank"),
    ("Guaranty Trust", "058", "Guaranty Trust Bank"),
    ("Guaranty Trust Bank", "058", "Guaranty Trust Bank"),
    ("UBA", "033", "United Bank For Africa"),
    ("First Bank", "011", "First Bank of Nigeria"),
    ("FBN", "011", "First Bank of Nigeria"),
    ("FCMB", "214", "First City Monument Bank"),
    ("Sterling", "232", "Sterling Bank"),
    ("Wema", "035", "Wema Bank"),
    ("ALAT", "035A", "ALAT by WEMA"),
    ("Fidelity", "070", "Fidelity Bank"),
    ("Union Bank", "032", "Union Bank of Nigeria"),
    ("Polaris", "076", "Polaris Bank"),
    ("Stanbic IBTC", "221", "Stanbic IBTC Bank"),
    ("Ecobank", "050", "Ecobank Nigeria"),
    ("Keystone", "082", "Keystone Bank"),
    ("Providus", "101", "Providus Bank"),
    ("Kuda", "50211", "Kuda Bank"),
    ("Moniepoint", "50515", "Moniepoint MFB"),
    ("PalmPay", "999991", "PalmPay"),
    ("Opay", "999992", "OPay Digital Services Limited (OPay)"),
    ("Paycom", "999992", "OPay Digital Services Limited (OPay)"),
    ("Carbon", "565", "Carbon"),
    ("Jaiz", "301", "Jaiz Bank"),
    ("Diamond", "063", "Access Bank (Diamond)"),
]


@pytest.mark.parametrize(("said", "code", "name"), SPOKEN)
def test_a_bank_said_the_way_people_say_it_is_the_banks_code_on_paystacks_list(said, code, name):
    assert resolve_bank(said) == (name, code)


@pytest.mark.parametrize(
    "said",
    ["gtb", "GTB", " G T B ", "g.t.b", "G-T-B", "Gtb!", "GT Bank", "G.T. Bank", "gtBANK", "  gtbank  "],
)
def test_case_spacing_and_punctuation_do_not_matter(said):
    assert resolve_bank(said).code == "058"


def test_spellings_with_no_space_or_extra_marks_meet_the_same_bank():
    assert resolve_bank("U.B.A").code == resolve_bank("uba").code == "033"
    assert resolve_bank("Palm Pay").code == resolve_bank("PALMPAY").code == "999991"
    assert resolve_bank("O-Pay").code == "999992"
    assert normalise("Zénith  Bänk") == "zenith bank" and normalise("U&C") == "u and c"


def test_access_alone_is_access_bank_and_the_diamond_entry_needs_its_own_word():
    assert resolve_bank("Access").code == resolve_bank("Access Bank").code == "044"
    assert resolve_bank("Access Bank (Diamond)").code == resolve_bank("Access Diamond").code == "063"
    assert resolve_bank("Diamond Bank").code == "063"


def test_alat_and_wema_are_two_banks_as_paystack_lists_them():
    assert {resolve_bank("Wema").code, resolve_bank("ALAT").code} == {"035", "035A"}


@pytest.mark.parametrize("said", ["First", "Kolomoni", "Tatum", "Paystack", "bank"])
def test_a_name_that_fits_several_banks_is_refused_with_the_nearest(said):
    with pytest.raises(BankAmbiguous) as refused:
        resolve_bank(said)
    candidates = refused.value.candidates
    assert 2 <= len(candidates) <= MAX_CANDIDATES
    assert len({bank.code for bank in candidates}) == len(candidates)


def test_first_names_the_banks_people_mean_before_the_rest():
    with pytest.raises(BankAmbiguous) as refused:
        resolve_bank("First")
    assert [bank.name for bank in refused.value.candidates[:2]] == [
        "First Bank of Nigeria",
        "First City Monument Bank",
    ]


@pytest.mark.parametrize(
    ("said", "nearest"),
    [
        ("Acess Bank", "Access Bank"),
        ("Zennith", "Zenith Bank"),
        ("united", "United Bank For Africa"),
        ("Guaranty Trst", "Guaranty Trust Bank"),
    ],
)
def test_a_name_that_is_not_a_bank_is_refused_and_the_nearest_bank_is_named(said, nearest):
    with pytest.raises(BankNotFound) as refused:
        resolve_bank(said)
    assert not isinstance(refused.value, BankAmbiguous)
    assert refused.value.candidates[0].name == nearest
    assert len(refused.value.candidates) <= MAX_CANDIDATES


@pytest.mark.parametrize("said", ["", "   ", "???", "12345", "xyz bank", "Nova Scotia Credit Union"])
def test_nonsense_is_refused_and_a_guess_is_not_offered(said):
    with pytest.raises(BankNotFound) as refused:
        resolve_bank(said)
    assert not isinstance(refused.value, BankAmbiguous)
    assert len(refused.value.candidates) <= MAX_CANDIDATES


def test_no_bank_of_the_list_resolves_to_another_bank_by_its_own_name():
    wrong = []
    for name, code, _, _ in BANK_LIST:
        try:
            found = resolve_bank(name)
        except BankAmbiguous:
            continue
        if found.code != code:
            wrong.append((name, code, found))
    assert wrong == []


def test_every_hand_written_spelling_belongs_to_a_bank_on_the_list_and_to_one_bank_only():
    listed = {code for _, code, _, _ in BANK_LIST}
    assert set(BANK_ALIASES) <= listed
    owners: dict[str, set[str]] = {}
    for code, spellings in BANK_ALIASES.items():
        for spelling in spellings:
            owners.setdefault(normalise(spelling).replace(" ", ""), set()).add(code)
    assert {key: codes for key, codes in owners.items() if len(codes) > 1} == {}


def test_every_hand_written_spelling_resolves_to_its_own_bank():
    for code, spellings in BANK_ALIASES.items():
        for spelling in spellings:
            assert resolve_bank(spelling).code == code, spelling


def test_the_list_is_paystacks_naira_banks_with_the_codes_the_first_prompt_was_written_from_memory_for():
    assert len(BANK_LIST) == 287
    for code, name in [
        ("044", "Access Bank"),
        ("057", "Zenith Bank"),
        ("058", "Guaranty Trust Bank"),
        ("033", "United Bank For Africa"),
        ("011", "First Bank of Nigeria"),
        ("50211", "Kuda Bank"),
        ("999992", "OPay Digital Services Limited (OPay)"),
        ("999991", "PalmPay"),
        ("035", "Wema Bank"),
        ("232", "Sterling Bank"),
    ]:
        assert bank_of_code(code).name == name


def test_banks_that_share_a_code_show_the_first_name_and_an_unknown_code_is_none():
    assert bank_of_code("50572").name == "BANKIT MFB"
    assert bank_of_code("000") is None
    assert all(len(row) == 4 and row[3] == "nuban" for row in BANK_LIST)
