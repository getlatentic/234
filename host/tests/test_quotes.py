# SPDX-License-Identifier: AGPL-3.0-or-later
"""Which quotes are still open, and where the flow of the latest one begins."""

import pytest

from turns.compaction import quotes

from .log_builder import Log

NOW = 1_790_000_000_000
HOUR = 3_600_000


@pytest.mark.parametrize(
    ("phase", "open_now"),
    [
        ("awaiting_approval", True),
        ("awaiting_checkout", True),
        ("awaiting_otp", True),
        ("processing", True),
        ("succeeded", False),
        ("attention", False),
        ("failed", False),
        ("abandoned", False),
        ("expired", False),
        ("declined", False),
        ("unavailable", False),
    ],
)
def test_a_quote_is_open_while_it_waits_on_the_person_or_the_payment(phase, open_now):
    log = Log()
    log.quote("qt-a", 1000, "airtime", phase)
    assert [q.is_open(NOW) for q in quotes.quotes_of(log.events)] == [open_now]


def test_a_quote_nobody_approved_is_closed_once_its_time_has_run_out():
    log = Log()
    log.quote("qt-late", 1000, "airtime", expires_ms=NOW - HOUR)
    log.quote("qt-in-time", 1000, "airtime", expires_ms=NOW + HOUR)
    log.quote("qt-paying", 1000, "airtime", "awaiting_checkout", expires_ms=NOW - HOUR)
    found = {q.ref: q.is_open(NOW) for q in quotes.quotes_of(log.events)}
    assert found == {"qt-late": False, "qt-in-time": True, "qt-paying": True}


def test_a_quote_stands_as_its_latest_state_says():
    log = Log()
    log.quote("qt-a", 50000, "airtime")
    log.state("qt-a", "succeeded", 50000, "airtime")
    (found,) = quotes.quotes_of(log.events)
    assert (found.phase, found.kobo, found.seq) == ("succeeded", 50000, 3)
    assert found.what.endswith("airtime")


def test_the_flow_of_a_quote_starts_at_the_reply_that_made_it():
    log = Log()
    log.turn("hello", "hi")
    log.user("airtime please")
    reply_seq = log.last + 1
    log.quote("qt-a", 1000, "airtime", says="Here is your quote")
    log.reply("Please check the card.")
    (found,) = quotes.quotes_of(log.events)
    assert quotes.flow_start(log.events, found) == reply_seq


def test_a_quote_a_menu_made_starts_at_its_own_card():
    log = Log()
    log.user("menu")
    card = log.add(
        "card",
        {"result": {"structuredContent": {"quote": {"id": "qt-m", "phase": "awaiting_approval"}}}},
        ref="qt-m",
    )
    (found,) = quotes.quotes_of(log.events)
    assert quotes.flow_start(log.events, found) == card.seq


def test_only_the_latest_open_quote_sets_the_floor():
    log = Log()
    log.quote("qt-old", 1000, "airtime")
    log.turn("more", "sure")
    newer = log.last + 1
    log.quote("qt-new", 2000, "airtime")
    assert quotes.open_floor(log.events, NOW) == newer
    log.state("qt-new", "declined")
    assert quotes.open_floor(log.events, NOW) == 1
    log.state("qt-old", "succeeded")
    assert quotes.open_floor(log.events, NOW) is None


def test_the_open_quotes_before_a_cut_are_those_whose_cards_are_before_it():
    log = Log()
    log.quote("qt-a", 1000, "airtime")
    cut = log.last
    log.quote("qt-b", 1000, "airtime")
    assert quotes.open_refs_before(log.events, cut, NOW) == {"qt-a"}
