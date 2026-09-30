# SPDX-License-Identifier: AGPL-3.0-or-later
"""The facts a summary must keep, found by rule: what the person typed and what the connectors quoted."""

import pytest

from turns.compaction import facts
from turns.compaction.facts import Facts

from .log_builder import Log

PHONE = "7031234567"


@pytest.mark.parametrize(
    ("text", "kobo"),
    [
        ("Buy ₦5,000 airtime", {500000}),
        ("send N5000 to Ada", {500000}),
        ("send n5000 to Ada", set()),
        ("send 5k to Ada", {500000}),
        ("₦2.5k please", {250000}),
        ("2500 naira only", {250000}),
        ("NGN 1,000", {100000}),
        ("₦500.50", {50050}),
        ("amount_kobo 50000", set()),
        ("50000 kobo", {50000}),
        ("₦5,000, then ₦200.", {500000, 20000}),
        ("I have 5 km to go and 1000 people", set()),
        ("call 07031234567", set()),
        ("Quote qt-0123456789abcdef0123 is open", set()),
    ],
)
def test_the_amounts_a_person_writes_are_read_in_kobo(text, kobo):
    assert facts.facts_in_text(text).amounts == kobo


@pytest.mark.parametrize(
    "text",
    [
        "07031234567",
        "0703 123 4567",
        "0703-123-4567",
        "+234 703 123 4567",
        "+2347031234567",
        "2347031234567",
        "call me on 07031234567.",
    ],
)
def test_a_phone_number_is_one_number_however_it_is_written(text):
    found = facts.facts_in_text(text)
    assert found.phones == {PHONE} and not found.accounts


@pytest.mark.parametrize("text", ["0123456789", "0123 456 789", "012-345-6789", "GTBank 0123456789 Ada"])
def test_an_account_number_is_ten_digits_however_it_is_grouped(text):
    found = facts.facts_in_text(text)
    assert found.accounts == {"0123456789"} and not found.phones


def test_a_quote_id_holds_no_account_number():
    assert not facts.facts_in_text("qt-1234567890abcdef1234 and qt-00000000001234567890")


def test_the_facts_of_a_log_are_what_the_person_typed_and_what_was_quoted_not_what_the_assistant_said():
    log = Log()
    log.user("Send 5k to Ada, GTBank 0123456789")
    log.reply("Sending ₦9,999 to 0999999999")
    log.quote("qt-a", 50000, "MTN airtime to 0703 123 4567")
    found = facts.facts_of_events(log.events)
    assert found.amounts == {500000, 50000}
    assert found.accounts == {"0123456789"} and found.phones == {PHONE}


def test_a_quote_counts_with_the_amount_the_ledger_holds():
    log = Log()
    log.quote("qt-a", 123456, "payment")
    assert 123456 in facts.facts_of_events(log.events).amounts


REQUIRED = Facts(
    frozenset({500000, 100000}), frozenset({PHONE}), frozenset({"0123456789"}), frozenset({"qt-a"})
)


@pytest.mark.parametrize(
    "summary",
    [
        "Paid ₦5,000 and ₦1,000 to 07031234567; account 0123456789; qt-a is open.",
        "5000 and 1000 naira, 0703 123 4567, 012-345-6789 (0123 456 789), quote qt-a.",
        "5k, 1k, +2347031234567, account 0123456789, qt-a",
        "500000 kobo... no: 500,000 is ₦5,000.00; ₦1,000; 07031234567; 0123456789; qt-a",
    ],
)
def test_a_summary_that_states_every_fact_in_any_form_is_complete(summary):
    assert not facts.missing_from(summary, REQUIRED, Facts())


@pytest.mark.parametrize(
    ("summary", "missing"),
    [
        ("₦5,000, 07031234567, 0123456789, qt-a", Facts(amounts=frozenset({100000}))),
        ("₦5,000 and ₦1,000, 07031234568, 0123456789, qt-a", Facts(phones=frozenset({PHONE}))),
        ("₦5,000 and ₦1,000, 07031234567, 0123456780, qt-a", Facts(accounts=frozenset({"0123456789"}))),
        ("₦5,000 and ₦1,000, 07031234567, 0123456789", Facts(open_quotes=frozenset({"qt-a"}))),
        ("₦50.00 and ₦1,000, 07031234567, 0123456789, qt-a", Facts(amounts=frozenset({500000}))),
        ("nothing", REQUIRED),
    ],
    ids=["an amount", "a digit of a phone", "a digit of an account", "an open quote", "a rounding", "all"],
)
def test_what_a_summary_dropped_or_changed_is_named(summary, missing):
    assert facts.missing_from(summary, REQUIRED, Facts()) == missing


def test_a_fact_that_the_kept_messages_hold_is_not_required_of_the_summary():
    kept = Facts(frozenset({500000}), frozenset({PHONE}))
    assert facts.missing_from("₦1,000 0123456789 qt-a", REQUIRED, kept) == Facts()


def test_a_bare_number_is_naira_and_never_kobo():
    wants_fifty_naira = Facts(amounts=frozenset({5000}))
    assert facts.missing_from("₦5,000 was paid", wants_fifty_naira, Facts()) == wants_fifty_naira
    assert not facts.missing_from("₦50 was paid", wants_fifty_naira, Facts())


def test_the_block_lists_every_fact_and_each_quote_with_the_state_it_is_in():
    log = Log()
    log.user("Send 5k to Ada, GTBank 0123456789, from 07031234567")
    log.quote("qt-paid", 500000, "transfer to Ada")
    log.state("qt-paid", "succeeded", 500000, "transfer to Ada")
    log.quote("qt-open", 50000, "airtime")
    block = facts.facts_block(log.events, log.last, now_ms=0)
    assert block.startswith(facts.FACTS_HEADING)
    for expected in (
        "₦5,000",
        "₦500",
        "07031234567",
        "0123456789",
        "qt-paid: succeeded",
        "qt-open: awaiting_approval (open)",
    ):
        assert expected in block
    assert block.index("qt-open") < block.index("qt-paid")


def test_the_block_names_only_what_the_cut_covers_but_shows_the_state_now():
    log = Log()
    log.quote("qt-old", 100000, "airtime")
    cut = log.last
    log.state("qt-old", "succeeded", 100000, "airtime")
    log.quote("qt-new", 777700, "payment")
    block = facts.facts_block(log.events, cut, now_ms=0)
    assert "qt-old: succeeded" in block and "qt-new" not in block and "₦7,777" not in block


def test_a_long_history_lists_the_open_and_latest_quotes_and_counts_the_rest():
    log = Log()
    for n in range(facts.LISTED_QUOTES + 10):
        log.quote(f"qt-{n}", 10000 + n * 100, "airtime")
        log.state(f"qt-{n}", "declined" if n % 2 else "succeeded", 10000, "airtime")
    block = facts.facts_block(log.events, log.last, now_ms=0)
    assert block.count("\n- qt-") == facts.LISTED_QUOTES
    assert "10 earlier quotes: 5 declined, 5 succeeded" in block
    assert f"qt-{facts.LISTED_QUOTES + 9}:" in block and "qt-0:" not in block


def test_the_block_can_be_taken_off_a_summary():
    assert facts.without_block(f"A summary.\n\n{facts.FACTS_HEADING}\namounts: ₦5") == "A summary."
    assert facts.without_block("No block.") == "No block."


def test_naira_is_written_with_kobo_only_when_there_is_some():
    assert facts.naira(500000) == "₦5,000" and facts.naira(50050) == "₦500.50" and facts.naira(5) == "₦0.05"


def test_a_log_with_nothing_to_record_has_no_block():
    log = Log()
    log.turn("hello there", "hi")
    assert facts.facts_block(log.events, log.last, now_ms=0) == ""
