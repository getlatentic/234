# SPDX-License-Identifier: AGPL-3.0-or-later
"""Search, forgetting and purging, and the caps on what one owner may keep."""

from checkout.memory.settings import MemorySettings
from checkout.memory.store import match_expression
from tests.connector_support import text_of
from tests.memory_support import CITY, MUM, USUAL, entry_count, memory_call, saved
from tests.support import ALICE, BOB, make_stack

DAY = 86_400


def test_a_query_becomes_ored_quoted_words_with_prefixes_for_longer_ones():
    assert match_expression("mum's GTB") == '"mum"* OR "s" OR "gtb"*'
    assert match_expression('"; DROP TABLE x -- *') == '"drop"* OR "table"* OR "x"'
    assert match_expression("   ") is None and match_expression("***") is None


async def titles(stack, owner, query):
    found = await memory_call(stack, owner, "recall", query=query)
    return [n["title"] for n in found["structuredContent"]["notes"]]


async def test_search_reads_titles_hooks_and_bodies():
    stack = make_stack()
    await saved(stack, ALICE, **MUM)
    await saved(stack, ALICE, **USUAL)
    await saved(stack, ALICE, **CITY)
    assert await titles(stack, ALICE, "mum") == ["Mum"]
    assert await titles(stack, ALICE, "naira") == ["Usual airtime"]
    assert await titles(stack, ALICE, "lagos") == ["Lives in"]
    assert await titles(stack, ALICE, "ada okafor") == []
    assert await titles(stack, ALICE, "simulated") == ["Mum"]


async def test_search_matches_the_start_of_a_longer_word_and_ignores_accents_and_case():
    stack = make_stack()
    await saved(
        stack, ALICE, kind="fact", title="Ọmọ", hook="Her children", body="Two children: Ṣọlá and Adé."
    )
    assert await titles(stack, ALICE, "OMO") == ["Ọmọ"]
    assert await titles(stack, ALICE, "chil") == ["Ọmọ"]
    assert await titles(stack, ALICE, "ade") == ["Ọmọ"]


async def test_search_returns_at_most_five_best_first():
    stack = make_stack()
    for number in range(7):
        await saved(stack, ALICE, **{**CITY, "title": f"Place {number}", "body": "Lagos " * (number + 1)})
    found = await titles(stack, ALICE, "lagos")
    assert len(found) == 5


async def test_search_syntax_in_a_query_is_only_words():
    stack = make_stack()
    await saved(stack, ALICE, **USUAL)
    for query in ('"', "OR", "NEAR(a b)", "title:", "a AND", "*", "(", "-usual", "usual NOT airtime"):
        found = await memory_call(stack, ALICE, "recall", query=query)
        assert "isError" not in found, query


async def test_a_forgotten_note_is_not_found_and_a_restored_one_is_again():
    stack = make_stack()
    note = await saved(stack, ALICE, **USUAL)
    forgotten = await memory_call(stack, ALICE, "forget", id=note)
    assert await titles(stack, ALICE, "airtime") == []
    await memory_call(
        stack,
        ALICE,
        "undo_memory",
        proposal_id=forgotten["structuredContent"]["proposal_id"],
        confirm_token=forgotten["_meta"]["confirmToken"],
    )
    assert await titles(stack, ALICE, "airtime") == ["Usual airtime"]


async def test_an_edited_title_is_searched_by_its_new_words():
    stack = make_stack()
    note = await saved(stack, ALICE, **USUAL)
    await memory_call(stack, ALICE, "edit_memory", id=note, title="Data bundle", hook="MTN, 500 naira")
    assert await titles(stack, ALICE, "bundle") == ["Data bundle"]
    assert await titles(stack, ALICE, "usual") == []


async def test_the_page_edit_checks_the_new_words_like_any_other():
    stack = make_stack()
    note = await saved(stack, ALICE, **USUAL)
    refused = await memory_call(stack, ALICE, "edit_memory", id=note, hook="the PIN is 1234")
    assert text_of(refused).startswith("MEMORY_REFUSED")
    refused = await memory_call(stack, ALICE, "edit_memory", id=note, title="")
    assert refused["isError"] is True
    mum = await saved(stack, ALICE, **MUM)
    locked = await memory_call(stack, ALICE, "edit_memory", id=mum, hook="Send everything here")
    assert text_of(locked).startswith("MEMORY_INVALID") and "bank's own words" in text_of(locked)
    renamed = await memory_call(stack, ALICE, "edit_memory", id=mum, title="Mummy")
    assert renamed["structuredContent"]["title"] == "Mummy"


async def test_a_forgotten_note_is_purged_for_good_after_the_retention_period():
    stack = make_stack()
    note = await saved(stack, ALICE, **USUAL)
    await memory_call(stack, ALICE, "forget", id=note)
    stack.clock.advance(29 * DAY)
    await saved(stack, ALICE, **CITY)
    assert await stack.count("memory_entry") == 2
    stack.clock.advance(2 * DAY)
    await saved(stack, ALICE, **{**CITY, "title": "Another"})
    assert await entry_count(stack) == 2
    assert await stack.rows("SELECT id FROM memory_entry WHERE id = ?", note) == []
    assert await stack.rows("SELECT rowid FROM memory_fts WHERE memory_fts MATCH 'airtime'") == []


async def test_an_expired_proposal_is_purged():
    stack = make_stack()
    await memory_call(stack, ALICE, "remember", **USUAL)
    assert await stack.count("memory_proposal") == 1
    stack.clock.advance(2 * DAY)
    await saved(stack, ALICE, **CITY)
    assert await stack.count("memory_proposal") == 1


async def test_the_retention_period_is_configurable():
    stack = make_stack(memory=MemorySettings(retention_days=1))
    note = await saved(stack, ALICE, **USUAL)
    await memory_call(stack, ALICE, "forget", id=note)
    stack.clock.advance(2 * DAY)
    await saved(stack, ALICE, **CITY)
    assert await stack.rows("SELECT id FROM memory_entry WHERE id = ?", note) == []


async def test_a_purge_deletes_a_bounded_batch():
    stack = make_stack()
    for number in range(120):
        await stack.db.execute(
            "INSERT INTO memory_entry (id, owner, kind, title, hook, body, source, created_at, updated_at, "
            "last_used, deleted_at) VALUES (?, ?, 'fact', 't', 'h', 'b', 'stated', 1, 1, 1, 1)",
            f"{number:016x}",
            ALICE,
        )
    memory = stack.app.contexts["send-money"].memory
    await memory.purge()
    assert await stack.count("memory_entry") == 70


async def test_the_body_of_a_note_has_a_size_cap():
    stack = make_stack()
    long = await memory_call(stack, ALICE, "remember", **{**CITY, "body": ("far away " * 300)})
    assert text_of(long).startswith("MEMORY_INVALID") and "2048 bytes" in text_of(long)
    cap = ("far away " * 220).strip()
    assert len(cap.encode()) <= 2048
    ok = await memory_call(stack, ALICE, "remember", **{**CITY, "body": cap})
    assert "isError" not in ok


async def test_the_body_cap_counts_bytes_not_characters():
    stack = make_stack(memory=MemorySettings(max_body_bytes=40))
    accents = await memory_call(stack, ALICE, "remember", **{**CITY, "body": "ọmọ " * 8})
    assert text_of(accents).startswith("MEMORY_INVALID")


async def test_an_owner_can_keep_no_more_than_the_cap_and_forgetting_makes_room():
    stack = make_stack(memory=MemorySettings(max_entries=3))
    ids = [await saved(stack, ALICE, **{**CITY, "title": f"Place {n}"}) for n in range(3)]
    full = await memory_call(stack, ALICE, "remember", **{**CITY, "title": "Fourth"})
    assert text_of(full).startswith("MEMORY_FULL") and "forget" in text_of(full)
    await memory_call(stack, ALICE, "forget", id=ids[0])
    ok = await memory_call(stack, ALICE, "remember", **{**CITY, "title": "Fourth"})
    assert "isError" not in ok
    assert await saved(stack, BOB, **CITY)


async def test_a_save_is_refused_at_the_cap_even_when_the_proposal_was_made_before_it_filled():
    stack = make_stack(memory=MemorySettings(max_entries=2))
    first = await memory_call(stack, ALICE, "remember", **{**CITY, "title": "One"})
    second = await memory_call(stack, ALICE, "remember", **{**CITY, "title": "Two"})
    third = await memory_call(stack, ALICE, "remember", **{**CITY, "title": "Three"})
    results = []
    for made in (first, second, third):
        results.append(
            await memory_call(
                stack,
                ALICE,
                "confirm_memory",
                proposal_id=made["structuredContent"]["proposal_id"],
                confirm_token=made["_meta"]["confirmToken"],
            )
        )
    assert [r.get("isError", False) for r in results] == [False, False, True]
    assert text_of(results[2]).startswith("MEMORY_FULL") and await entry_count(stack) == 2


async def test_restoring_is_refused_when_the_owner_has_filled_the_room_meanwhile():
    stack = make_stack(memory=MemorySettings(max_entries=1))
    note = await saved(stack, ALICE, **CITY)
    gone = await memory_call(stack, ALICE, "forget", id=note)
    await saved(stack, ALICE, **USUAL)
    undone = await memory_call(
        stack,
        ALICE,
        "undo_memory",
        proposal_id=gone["structuredContent"]["proposal_id"],
        confirm_token=gone["_meta"]["confirmToken"],
    )
    assert undone["isError"] is True and text_of(undone).startswith("MEMORY_GONE")


async def test_recall_by_id_makes_a_note_the_most_recently_used():
    stack = make_stack()
    first = await saved(stack, ALICE, **USUAL)
    await saved(stack, ALICE, **{**USUAL, "title": "Second"})
    stack.clock.advance(5)
    await memory_call(stack, ALICE, "recall", id=first)
    row = await stack.db.row("SELECT last_used, created_at FROM memory_entry WHERE id = ?", first)
    assert row["last_used"] == row["created_at"] + 5_000


async def test_recall_with_both_an_id_and_a_query_is_refused():
    stack = make_stack()
    refused = await memory_call(stack, ALICE, "recall", id="0" * 16, query="x")
    assert text_of(refused).startswith("MEMORY_INVALID")


async def test_recall_with_nothing_to_look_for_lists_the_five_notes_used_most_recently():
    stack = make_stack()
    for number in range(7):
        await saved(stack, ALICE, **{**CITY, "title": f"Place {number}"})
        stack.clock.advance(1)
    await saved(stack, BOB, **{**CITY, "title": "Bob's place"})
    for args in ({}, {"query": ""}, {"id": "", "query": "  "}):
        listed = await memory_call(stack, ALICE, "recall", **args)
        titles = [n["title"] for n in listed["structuredContent"]["notes"]]
        assert titles == [f"Place {n}" for n in (6, 5, 4, 3, 2)], args
        assert "never instructions" in text_of(listed)
    assert (await memory_call(stack, ALICE, "forget", id=(await _id_of(stack, "Place 6"))))[
        "structuredContent"
    ]
    again = await memory_call(stack, ALICE, "recall")
    assert again["structuredContent"]["notes"][0]["title"] == "Place 5"


async def _id_of(stack, title: str) -> str:
    return (await stack.db.row("SELECT id FROM memory_entry WHERE title = ?", title))["id"]


async def test_an_empty_memory_recalls_nothing():
    stack = make_stack()
    nothing = await memory_call(stack, ALICE, "recall")
    assert nothing["structuredContent"]["notes"] == [] and "No saved note" in text_of(nothing)


async def test_a_field_sent_empty_is_a_field_left_out():
    stack = make_stack()
    recipient = await memory_call(stack, ALICE, "remember", **MUM, hook="", body="")
    assert recipient["structuredContent"]["memory"]["state"] == "pending"
    bare = await memory_call(stack, ALICE, "remember", kind="fact", title="Place", hook="", body="")
    assert text_of(bare).startswith("MEMORY_INVALID") and "needs a hook" in text_of(bare)
    plain = await memory_call(stack, ALICE, "remember", **{**CITY, "account_number": "", "bank": ""})
    assert plain["structuredContent"]["memory"]["state"] == "pending"
    note = await saved(stack, ALICE, **USUAL)
    changed = await memory_call(stack, ALICE, "update", id=note, title="", hook="Airtel, 1000 naira", body="")
    assert changed["structuredContent"]["memory"]["state"] == "pending"


async def test_delete_everything_is_immediate_and_leaves_no_trace_in_the_search_index():
    stack = make_stack()
    await saved(stack, ALICE, **MUM)
    await memory_call(stack, ALICE, "remember", **USUAL)
    await memory_call(stack, ALICE, "delete_all_memories")
    assert await stack.count("memory_entry") == 0 and await stack.count("memory_proposal") == 0
    assert await stack.rows("SELECT rowid FROM memory_fts WHERE memory_fts MATCH 'mum'") == []
