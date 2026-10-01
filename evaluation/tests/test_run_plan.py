# SPDX-License-Identifier: AGPL-3.0-or-later
"""A run that lost draws to infrastructure is completed, not re-rolled: only the draws that never got an
answer are made again, and a wrong answer is kept."""

import argparse
import json

from evaluation.cases import load_cases
from evaluation.redo import lost, plan

CASES = [c for c in load_cases() if c.split == "memory"][:3]


def draw(case, number, error=None, infra=False, ok=True):
    return {"case": case.id, "draw": number, "error": error, "score": {"ok": ok, "infra": infra}}


def args(redo="", draws=2):
    return argparse.Namespace(redo=redo, draws=draws)


def test_a_draw_that_failed_to_get_an_answer_is_lost_and_a_wrong_answer_is_not():
    assert lost(draw(CASES[0], 0, error="SetupFailed: HTTP 429"))
    assert lost(draw(CASES[0], 0, infra=True, ok=False))
    assert not lost(draw(CASES[0], 0, ok=False))
    assert not lost(draw(CASES[0], 0))


def test_without_a_file_every_case_is_drawn_for_every_round():
    drawn, kept = plan(CASES, args())
    assert [(c.id, n) for c, n in drawn] == [(c.id, n) for n in range(2) for c in CASES] and kept == []


def test_with_a_file_only_the_lost_draws_are_made_again_and_the_rest_are_kept_as_they_were(tmp_path):
    first, second, third = CASES
    rows = [
        draw(first, 0),
        draw(second, 0, ok=False),
        draw(third, 0, error="SetupFailed: HTTP 429"),
        draw(first, 1, infra=True, ok=False),
    ]
    path = tmp_path / "earlier.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    drawn, kept = plan(CASES, args(redo=str(path)))
    assert [(c.id, n) for c, n in drawn] == [(third.id, 0), (first.id, 1)]
    assert kept == rows[:2]


def test_a_case_that_is_no_longer_chosen_is_not_made_again(tmp_path):
    path = tmp_path / "earlier.jsonl"
    path.write_text(json.dumps(draw(CASES[0], 0, error="x")) + "\n")
    drawn, _ = plan(CASES[1:], args(redo=str(path)))
    assert drawn == []
