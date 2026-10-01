# SPDX-License-Identifier: AGPL-3.0-or-later
"""The memory index: one line per note, grouped in a fixed order, newest use first, within a token budget,
read in one query."""

import random

from checkout.memory.index import omitted_line, render_index, tokens_of
from checkout.memory.settings import MemorySettings
from tests.memory_support import CITY, MUM, USUAL, memory_call, saved
from tests.support import ALICE, BOB, make_stack


def row(kind: str, number: int, title: str | None = None, hook: str = "a hook") -> dict:
    return {"id": f"{number:016x}", "kind": kind, "title": title or f"{kind} {number}", "hook": hook}


def test_an_empty_memory_has_an_empty_index():
    assert render_index([], 1500) == ""


def test_the_index_has_one_line_per_note_and_a_heading_per_group_in_a_fixed_order():
    rows = [row("fact", 1), row("preference", 2), row("recipient", 3), row("fact", 4), row("preference", 5)]
    text = render_index(rows, 1500)
    assert text.splitlines() == [
        "## Recipients",
        f"- [recipient 3]({3:016x}) — a hook",
        "## Preferences",
        f"- [preference 2]({2:016x}) — a hook",
        f"- [preference 5]({5:016x}) — a hook",
        "## Facts",
        f"- [fact 1]({1:016x}) — a hook",
        f"- [fact 4]({4:016x}) — a hook",
    ]


def test_a_group_with_no_note_has_no_heading():
    text = render_index([row("fact", 1)], 1500)
    assert text.splitlines()[0] == "## Facts" and "Recipients" not in text and "Preferences" not in text


def test_the_same_rows_give_the_same_text():
    rows = [row("fact", n) for n in range(30)]
    assert render_index(rows, 400) == render_index(list(rows), 400)


def test_notes_that_do_not_fit_are_counted_in_a_last_line():
    rows = [row("fact", n, hook="x" * 100) for n in range(40)]
    text = render_index(rows, 300)
    lines = text.splitlines()
    shown = [line for line in lines if line.startswith("- [")]
    assert 0 < len(shown) < 40 and lines[-1] == omitted_line(40 - len(shown))
    assert lines[-1].endswith("use recall")


def test_the_index_never_goes_over_its_budget():
    generator = random.Random(7)
    for _ in range(200):
        rows = [
            row(
                generator.choice(["recipient", "preference", "fact"]), n, hook="h" * generator.randint(1, 120)
            )
            for n in range(generator.randint(0, 80))
        ]
        budget = generator.choice([20, 60, 150, 400, 1500])
        text = render_index(rows, budget)
        assert tokens_of(text) <= budget or text.count("\n") == 0, (budget, tokens_of(text))


def test_a_full_house_of_notes_fits_the_default_budget_or_says_how_many_do_not():
    rows = [row("fact", n, hook="y" * 120) for n in range(200)]
    text = render_index(rows, MemorySettings().index_tokens)
    assert tokens_of(text) <= 1500 and "more: use recall" in text


async def test_the_index_of_an_owner_is_built_from_that_owners_notes_alone():
    stack = make_stack()
    await saved(stack, ALICE, **MUM)
    await saved(stack, ALICE, **USUAL)
    await saved(stack, BOB, **CITY)
    mine = (await memory_call(stack, ALICE, "memory_index"))["structuredContent"]
    theirs = (await memory_call(stack, BOB, "memory_index"))["structuredContent"]
    assert mine["entries"] == 2 and theirs["entries"] == 1
    assert "Mum" in mine["index"] and "Lives in" not in mine["index"]
    assert "Lives in" in theirs["index"] and "Mum" not in theirs["index"]


async def test_a_recipient_line_shows_the_banks_name_and_only_the_last_four_digits():
    stack = make_stack()
    await saved(stack, ALICE, **MUM)
    index = (await memory_call(stack, ALICE, "memory_index"))["structuredContent"]["index"]
    assert "— Guaranty Trust Bank, SIMULATED ACCOUNT 6789, ends 6789" in index
    assert "0123456789" not in index and "bodies" not in index


async def test_the_most_recently_used_note_comes_first_in_its_group():
    stack = make_stack()
    first = await saved(stack, ALICE, **USUAL)
    await saved(stack, ALICE, **{**USUAL, "title": "Second"})
    stack.clock.advance(60)
    await memory_call(stack, ALICE, "recall", id=first)
    index = (await memory_call(stack, ALICE, "memory_index"))["structuredContent"]["index"]
    lines = [line for line in index.splitlines() if line.startswith("- [")]
    assert lines[0].startswith("- [Usual airtime]") and lines[1].startswith("- [Second]")


async def test_the_index_is_one_range_scan_of_the_owners_live_rows_with_no_sort():
    stack = make_stack()
    plan = await stack.rows(
        "EXPLAIN QUERY PLAN SELECT id, kind, title, hook FROM memory_entry "
        "WHERE owner = ? AND deleted_at IS NULL ORDER BY last_used DESC LIMIT ?",
        ALICE,
        200,
    )
    detail = " ".join(str(r["detail"]) for r in plan)
    assert "memory_entry_live" in detail and "TEMP B-TREE" not in detail


async def test_a_forgotten_note_is_not_in_the_index():
    stack = make_stack()
    note = await saved(stack, ALICE, **CITY)
    await memory_call(stack, ALICE, "forget", id=note)
    assert (await memory_call(stack, ALICE, "memory_index"))["structuredContent"]["index"] == ""


async def test_the_index_is_cut_at_the_configured_budget():
    stack = make_stack(memory=MemorySettings(index_tokens=60))
    for number in range(8):
        await saved(stack, ALICE, **{**CITY, "title": f"Place {number}", "hook": "far away " * 8})
    index = (await memory_call(stack, ALICE, "memory_index"))["structuredContent"]
    assert tokens_of(index["index"]) <= 60 and index["index"].endswith("use recall")
