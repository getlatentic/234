# SPDX-License-Identifier: AGPL-3.0-or-later
import pytest

from evaluation.stats import cases_passing_every_draw, group_rates, latency_summary, rate, wilson


def test_wilson_matches_known_values():
    assert wilson(5, 10) == pytest.approx((0.2366, 0.7634), abs=1e-3)
    assert wilson(0, 10) == pytest.approx((0.0, 0.2775), abs=1e-3)
    assert wilson(10, 10) == pytest.approx((0.7225, 1.0), abs=1e-3)
    assert wilson(81, 100) == pytest.approx((0.7222, 0.8749), abs=1e-3)
    assert wilson(0, 0) == (0.0, 1.0)


def test_a_bigger_sample_is_narrower():
    small, large = wilson(9, 10), wilson(90, 100)
    assert small[1] - small[0] > large[1] - large[0]


def test_rate_prints_counts_share_and_interval():
    assert rate(12, 15) == "12/15 80% [55-93]"


def draws():
    return [
        {"case": "A", "c": "x", "ok": True},
        {"case": "A", "c": "x", "ok": False},
        {"case": "B", "c": "y", "ok": True},
    ]


def test_group_rates_follow_first_appearance():
    assert group_rates(draws(), lambda d: d["c"], lambda d: d["ok"]) == {"x": (1, 2), "y": (1, 1)}


def test_a_case_passes_only_when_every_draw_does():
    assert cases_passing_every_draw(draws(), lambda d: d["ok"]) == (1, 2)


def test_latency_summary():
    assert latency_summary([1.0, 2.0, 3.0, 10.0]) == "median 2.5 s, p90 10.0 s, max 10.0 s over 4 turns"
    assert latency_summary([]) == "no data"
