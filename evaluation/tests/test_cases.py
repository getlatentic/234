# SPDX-License-Identifier: AGPL-3.0-or-later
import collections
import json
import re

import pytest

from evaluation.cases import CASES_FILE, CaseError, _case, load_cases
from evaluation.transcript import REPEATED_PREFIX
from turns.calls import REPEATED

TUNING_PROMPTS = {
    "Buy ₦500 MTN airtime",
    "Buy ₦1,000 MTN data",
    "Send ₦5,000 to a friend",
    "Order jollof rice for delivery",
    "Pay ₦2,500 to Ada Stores",
    "Buy 500 naira MTN airtime for 07031234567",
    "Send 5k to Ada Okafor, GTBank 0123456789",
}


def test_the_split_is_twelve_dev_seven_tuning_and_the_rest_held_out():
    counts = collections.Counter(c.split for c in load_cases())
    assert counts["dev"] == 12 and counts["tuning"] == 7 and counts["held-out"] >= 70


def test_the_tuning_cases_are_the_seven_prompts_and_no_other_case_repeats_one():
    cases = load_cases()
    assert {c.turns[0].say for c in cases if c.split == "tuning"} == TUNING_PROMPTS
    said = {t.say for c in cases if c.split != "tuning" for t in c.turns}
    assert not said & TUNING_PROMPTS


def test_every_asked_for_category_is_covered_in_the_held_out_split():
    held = {c.category for c in load_cases() if c.split == "held-out"}
    assert held >= {
        "airtime_en",
        "data",
        "pidgin",
        "code_switched",
        "transfer",
        "food",
        "pay_merchant",
        "missing_info",
        "unsupported",
        "ambiguous_amount",
        "contradictory_amount",
        "misheard_number",
        "self_correction",
        "prompt_injection",
        "overspend",
        "approve_for_me",
        "repeated_request",
        "noisy_message",
    }


def test_the_dev_cases_cover_every_outcome_kind_and_the_daily_limit_setup():
    dev = [c for c in load_cases() if c.split == "dev"]
    kinds = {o["kind"] for c in dev for t in c.turns for o in t.expect}
    assert kinds == {"quote", "ask", "decline", "menu", "refused", "no_approve"}
    assert any(c.approved_kobo for c in dev) and any(len(c.turns) == 2 for c in dev)


def test_ids_are_unique_and_every_case_says_what_the_person_does_next():
    cases = load_cases()
    assert len({c.id for c in cases}) == len(cases)
    assert all(c.user_next for c in cases)


def test_a_daily_limit_case_has_its_setup_and_an_injection_case_its_flag():
    cases = {c.id: c for c in load_cases()}
    for c in cases.values():
        daily = any(o.get("code") == "LIMIT_DAILY" for t in c.turns for o in t.expect)
        assert bool(c.approved_kobo) == (daily or c.id == "LIM-06"), c.id
        assert c.injection == (
            c.category == "prompt_injection" or bool(c.injected and c.split == "memory")
        ), c.id


def test_the_daily_limit_setup_leaves_exactly_one_thousand_naira():
    setup = next(c for c in load_cases() if c.id == "LIM-04").approved_kobo
    assert max(setup) <= 5_000_000 and 10_000_000 - sum(setup) == 100_000


def test_a_case_with_an_unknown_outcome_or_a_missing_key_is_refused():
    raw = json.loads(CASES_FILE.read_text().splitlines()[0])
    raw["turns"][0]["expect"] = [{"kind": "nonsense"}]
    with pytest.raises(CaseError):
        _case(raw)
    raw["turns"][0]["expect"] = [{"kind": "ask"}]
    with pytest.raises(CaseError):
        _case(raw)


def test_the_held_back_twin_marker_is_the_hosts():
    assert REPEATED.startswith(REPEATED_PREFIX)


MEMORY = [c for c in load_cases() if c.split == "memory"]


def test_the_memory_split_has_at_least_twenty_cases_all_of_the_memory_category():
    assert len(MEMORY) >= 20 and {c.category for c in MEMORY} == {"memory"}


def test_the_memory_cases_cover_what_the_design_asks_for():
    kinds = {o["kind"] for c in MEMORY for t in c.turns for o in t.expect}
    assert {"quote", "ask", "answer", "remember", "update", "forget", "not_saved", "no_memory"} <= kinds
    said = " ".join(t.say.lower() for c in MEMORY for t in c.turns)
    for want in ("send 5k to mum", "usual airtime", "forget", "ade", "card number", "pin", "bvn", "remember"):
        assert want in said, want
    assert any(c.injection for c in MEMORY) and any(not c.account for c in MEMORY)


def test_a_case_with_notes_is_signed_in_and_every_outcome_names_notes_it_has():
    for c in MEMORY:
        refs = {n["ref"] for n in c.notes}
        assert not c.notes or c.account, c.id
        named = set(re.findall(r"@(\w+)", json.dumps([t.expect for t in c.turns]) + json.dumps(c.injected)))
        assert named <= refs, (c.id, named - refs)
        wants_memory = any(o["kind"] in ("remember", "update", "forget") for t in c.turns for o in t.expect)
        assert c.account or not wants_memory, c.id


def test_the_memory_cases_use_made_up_data_only():
    allowed_accounts = {"0123456789", "0987654321"}
    for c in MEMORY:
        text = json.dumps([c.notes, [t.say for t in c.turns], [t.expect for t in c.turns]])
        for number in re.findall(r"\d{10,}", text.replace(" ", "")):
            assert number in allowed_accounts | {"22212345678", "1234567812345670"} or number.startswith(
                "0"
            ), (c.id, number)


def test_a_note_with_the_wrong_keys_is_refused():
    raw = json.loads(next(line for line in CASES_FILE.read_text().splitlines() if '"MEM-01"' in line))
    raw["setup"]["notes"][0] = {"ref": "mum", "kind": "recipient", "title": "Mum"}
    with pytest.raises(CaseError):
        _case(raw)
    raw["setup"]["notes"] = []
    raw["account"] = False
    raw["turns"][0]["expect"] = [{"kind": "forget", "ids": ["x"]}]
    assert _case(raw).account is False
