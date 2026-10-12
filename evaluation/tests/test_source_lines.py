# SPDX-License-Identifier: AGPL-3.0-or-later
"""The proof of a source line (#645): the pages a turn read, the lines the host showed, and the kinds of the
knowledge split that score them. No model and no stack."""

import pytest

from evaluation import source_lines
from evaluation.knowledge_data import corpus, knowledge_cases
from evaluation.score import score_turn

from .helpers import call, turn

CASES = {c.id: c for c in knowledge_cases()}
ROADS = "https://fixture-roads.gov.ng/licence/renewal"
INSPECTION = "https://fixture-roads.gov.ng/vehicle/inspection"
IDENTITY = "https://fixture-identity.gov.ng/correction"
READ = (
    f"[1] Renewing a driver's licence (Roads Agency (fixture); {ROADS}, retrieved 2026-10-01, official); "
    "id roads-licence-renewal#0\n> The renewal fee is 12,500 naira.\n>\n> A late fee is 5,000 naira.\n\n"
    f"[2] Yearly inspection of a private car (Roads Agency (fixture); {INSPECTION}, retrieved 2026-10-01, "
    "official); id vehicle-inspection#0\n> The inspection fee is 4,000 naira. A failed car comes back "
    "within 14 days.\n\n"
    f"[3] Correcting a name (Identity Commission (fixture); {IDENTITY}, retrieved 2026-10-01, official); "
    "id identity-record-correction#0\n> A correction is processed within 14 working days."
)
ROADS_LINE = f"Source: Renewing a driver's licence — {ROADS} (read 2026-10-01)"
INSPECTION_LINE = f"Source: Yearly inspection of a private car — {INSPECTION} (read 2026-10-01)"
IDENTITY_LINE = f"Source: Correcting a name — {IDENTITY} (read 2026-10-01)"


def record(reply: str, notices: list[str], say: str = "q", read: str = READ):
    searched = call("search_knowledge", "knowledge", {"query": "q"}, result=read[:200]) | {"read": read}
    return turn([searched], reply, say=say, end="completed") | {"notices": notices}


def test_the_pages_a_turn_read_are_found_by_link_and_by_title():
    found = source_lines.pages(READ)
    assert "12,500" in found[ROADS] and found[ROADS] == found["Renewing a driver's licence"]
    assert "4,000" in found[INSPECTION] and "4,000" not in found[ROADS]


def test_the_lines_the_host_shows_are_read_with_or_without_a_link():
    lines = source_lines.shown(record("r", [ROADS_LINE, "Source: A page (read 2026-10-01)", "Not in x"]))
    assert lines == [("Renewing a driver's licence", ROADS), ("A page", None)]


def test_a_figure_is_a_number_of_the_text_and_not_a_link_or_a_list_number():
    assert source_lines.figures(
        "Pay ₦12 500 or 12,500.00 at https://x.example.com/p2.\n1. Bring 2 photos"
    ) == {
        "12500",
        "12500.00",
        "2",
    }
    assert [source_lines.distinctive(f) for f in ("12500", "26.5", "14", "2026", "100")] == [
        True,
        True,
        False,
        False,
        True,
    ]


def test_a_line_whose_page_holds_the_figures_of_the_reply_is_proven():
    assert source_lines.unproven(record("The fee is 12,500 naira.", [ROADS_LINE]), READ, words_ok=False) == []


def test_a_line_whose_page_holds_none_of_the_figures_is_not():
    problems = source_lines.unproven(record("The fee is 12,500 naira.", [INSPECTION_LINE]), READ, False)
    assert len(problems) == 2 and "holds none of the figures" in problems[0]


def test_two_lines_together_may_hold_what_each_holds_only_in_part():
    reply = "A licence costs 12,500 naira and an inspection 4,000 naira."
    both = record(reply, [ROADS_LINE, INSPECTION_LINE])
    assert source_lines.unproven(both, READ, words_ok=False) == []
    missing = source_lines.unproven(record(reply, [ROADS_LINE]), READ, words_ok=False)
    assert missing == ["the lines shown leave out the figures ['4000']"]


def test_a_figure_the_person_gave_is_not_the_reply_s_claim():
    shown = record("Yes, 12,500 naira.", [INSPECTION_LINE], say="Is it 12,500 naira?")
    assert source_lines.unproven(shown, READ, words_ok=True) == []


def test_a_line_under_a_reply_with_no_figure_is_proven_only_where_words_are_enough():
    reply = record("You bring the old licence.", [ROADS_LINE])
    assert source_lines.unproven(reply, READ, words_ok=True) == []
    assert "no figure read" in source_lines.unproven(reply, READ, words_ok=False)[0]


def test_no_line_is_never_unproven():
    assert source_lines.unproven(record("The fee is 12,500 naira.", []), READ, words_ok=False) == []


def score(case_id: str, record: dict):
    return score_turn(CASES[case_id], 0, record)


def test_a_cited_answer_is_shown_only_the_page_that_holds_its_figure():
    reply = "A failed car comes back within 14 days."
    assert score("S04", record(reply, [INSPECTION_LINE])).ok
    wrong = score("S04", record(reply, [INSPECTION_LINE, IDENTITY_LINE]))
    assert not wrong.ok and "which the answer does not draw on" in " ".join(wrong.problems[0])


def test_an_answer_from_two_pages_shows_both_and_each_holds_its_figure():
    reply = "A business name costs 10,000 naira and a licence renewal 12,500 naira."
    read = READ + (
        "\n\n[4] Registering a business name (Corporate Registry (fixture); "
        "https://fixture-registry.gov.ng/business-name, retrieved 2026-10-01, official); "
        "id business-name-registration#0\n> A business name costs 10,000 naira."
    )
    registry = (
        "Source: Registering a business name — https://fixture-registry.gov.ng/business-name "
        "(read 2026-10-01)"
    )
    assert score("S10", record(reply, [registry, ROADS_LINE], read=read)).ok
    one = score("S10", record(reply, [ROADS_LINE], read=read))
    assert not one.ok and "business-name" in " ".join(one.problems[0])


@pytest.mark.parametrize(
    ("reply", "notices", "ok"),
    [
        ("The sources do not say whether you can renew abroad.", [], True),
        ("The sources do not say whether you can renew abroad.", [ROADS_LINE], False),
        ("Renewal costs 12,500 naira, but they do not say about abroad.", [ROADS_LINE], True),
        ("Renewal costs 12,500 naira, but they do not say about abroad.", [INSPECTION_LINE], False),
        ("You can renew abroad for 99,999 naira.", [], False),
    ],
)
def test_a_reply_the_pages_do_not_carry_is_shown_no_line_unless_a_figure_of_it_is_proven(reply, notices, ok):
    assert score("S06", record(reply, notices)).ok is ok


def test_the_new_kinds_have_outcomes_that_name_the_sources_and_links():
    known = corpus()
    both = CASES["S10"].turns[0].expect[0]
    assert [p["source"] for p in both["parts"]] == ["business-name-registration", "roads-licence-renewal"]
    assert CASES["S04"].turns[0].expect[0]["not_shown"] == [known["identity-record-correction"].meta["url"]]
    assert CASES["S06"].turns[0].expect[0]["near"] == ROADS
