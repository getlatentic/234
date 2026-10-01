# SPDX-License-Identifier: AGPL-3.0-or-later
"""Saving is never silent: a proposal writes nothing, and the one write is the card's Save with its token."""

import json

from tests.connector_support import text_of
from tests.memory_support import CITY, MUM, USUAL, decide, entry_count, memory_call, propose, saved
from tests.support import ALICE, BOB, make_stack


async def test_remember_makes_a_proposal_and_writes_no_note():
    stack = make_stack()
    proposed = await propose(stack, ALICE, "remember", **USUAL)
    assert await entry_count(stack) == 0
    assert await stack.count("memory_proposal") == 1
    view = proposed["structuredContent"]["memory"]
    assert view["state"] == "pending" and view["op"] == "remember" and view["title"] == "Usual airtime"


async def test_the_model_is_told_it_is_not_saved_and_never_sees_the_token():
    stack = make_stack()
    proposed = await propose(stack, ALICE, "remember", **USUAL)
    token = proposed["_meta"]["confirmToken"]
    assert token not in json.dumps(proposed["content"]) and token not in json.dumps(
        proposed["structuredContent"]
    )
    assert "Nothing is saved until the person presses Save" in text_of(proposed)


async def test_save_writes_the_note_once():
    stack = make_stack()
    proposed = await propose(stack, ALICE, "remember", **USUAL)
    first = await decide(stack, ALICE, proposed)
    again = await decide(stack, ALICE, proposed)
    assert (
        first["structuredContent"]["memory"]["state"]
        == "saved"
        == again["structuredContent"]["memory"]["state"]
    )
    assert await entry_count(stack) == 1
    row = await stack.db.row("SELECT * FROM memory_entry")
    assert row["id"] == proposed["structuredContent"]["proposal_id"]
    assert (row["kind"], row["title"], row["hook"], row["source"]) == (
        "preference",
        "Usual airtime",
        "MTN, 500 naira",
        "stated",
    )
    assert row["verified_at"] is None and row["created_at"] == row["last_used"]


async def test_no_discards_the_proposal_and_a_later_save_writes_nothing():
    stack = make_stack()
    proposed = await propose(stack, ALICE, "remember", **CITY)
    refused = await decide(stack, ALICE, proposed, "discard_memory")
    assert refused["structuredContent"]["memory"]["state"] == "discarded"
    after = await decide(stack, ALICE, proposed)
    assert after["structuredContent"]["memory"]["state"] == "discarded"
    assert await entry_count(stack) == 0


async def test_a_save_without_the_card_token_writes_nothing():
    stack = make_stack()
    proposed = await propose(stack, ALICE, "remember", **USUAL)
    pid = proposed["structuredContent"]["proposal_id"]
    for token in ("0" * 64, "not-the-token"):
        denied = await memory_call(stack, ALICE, "confirm_memory", proposal_id=pid, confirm_token=token)
        assert denied["isError"] is True and text_of(denied).startswith("MEMORY_DENIED")
    assert await entry_count(stack) == 0


async def test_a_token_made_for_one_proposal_does_not_save_another():
    stack = make_stack()
    first = await propose(stack, ALICE, "remember", **USUAL)
    second = await propose(stack, ALICE, "remember", **CITY)
    swapped = await memory_call(
        stack,
        ALICE,
        "confirm_memory",
        proposal_id=second["structuredContent"]["proposal_id"],
        confirm_token=first["_meta"]["confirmToken"],
    )
    assert text_of(swapped).startswith("MEMORY_DENIED") and await entry_count(stack) == 0


async def test_a_proposal_that_has_expired_is_not_saved():
    stack = make_stack()
    proposed = await propose(stack, ALICE, "remember", **USUAL)
    stack.clock.advance(86_400 + 1)
    done = await decide(stack, ALICE, proposed)
    assert done["structuredContent"]["memory"]["state"] == "expired" and await entry_count(stack) == 0


async def test_an_owner_who_leaves_many_unanswered_has_the_oldest_discarded():
    stack = make_stack()
    first = await propose(stack, ALICE, "remember", **{**USUAL, "title": "Note 0"})
    for number in range(1, 11):
        await propose(stack, ALICE, "remember", **{**USUAL, "title": f"Note {number}"})
    rows = await stack.rows("SELECT state, COUNT(*) AS n FROM memory_proposal GROUP BY state")
    assert {r["state"]: r["n"] for r in rows} == {"pending": 10, "discarded": 1}
    assert (await decide(stack, ALICE, first))["structuredContent"]["memory"]["state"] == "discarded"


async def test_a_proposal_cannot_be_saved_by_a_card_of_another_owner():
    stack = make_stack()
    proposed = await propose(stack, ALICE, "remember", **USUAL)
    stolen = await decide(stack, BOB, proposed)
    assert stolen["isError"] is True and text_of(stolen).startswith("MEMORY_DENIED")
    assert await entry_count(stack) == 0


async def test_a_duplicate_title_is_refused_with_the_id_to_update():
    stack = make_stack()
    first = await saved(stack, ALICE, **USUAL)
    again = await memory_call(stack, ALICE, "remember", **{**USUAL, "title": "usual AIRTIME"})
    assert text_of(again).startswith("MEMORY_INVALID") and first in text_of(again)
    other = await propose(stack, BOB, "remember", **USUAL)
    assert other["structuredContent"]["memory"]["state"] == "pending"


async def test_update_changes_a_note_only_after_save():
    stack = make_stack()
    note = await saved(stack, ALICE, **USUAL)
    proposed = await propose(stack, ALICE, "update", id=note, hook="Airtel, 1000 naira", body="Buys Airtel.")
    assert (await stack.db.row("SELECT hook FROM memory_entry"))["hook"] == "MTN, 500 naira"
    assert proposed["structuredContent"]["memory"]["op"] == "update"
    await decide(stack, ALICE, proposed)
    row = await stack.db.row("SELECT hook, body, title FROM memory_entry")
    assert (row["hook"], row["body"], row["title"]) == ("Airtel, 1000 naira", "Buys Airtel.", "Usual airtime")


async def test_update_that_changes_nothing_is_refused():
    stack = make_stack()
    note = await saved(stack, ALICE, **USUAL)
    same = await memory_call(stack, ALICE, "update", id=note, title="Usual airtime")
    assert text_of(same).startswith("MEMORY_INVALID")


async def test_a_recipient_update_to_another_account_is_looked_up_again():
    stack = make_stack()
    note = await saved(stack, ALICE, **MUM)
    proposed = await propose(stack, ALICE, "update", id=note, account_number="0987654321", bank="Zenith")
    assert "SIMULATED ACCOUNT 4321" in text_of(proposed)
    await decide(stack, ALICE, proposed)
    row = await stack.db.row("SELECT * FROM memory_entry")
    assert (row["account_number"], row["account_name"], row["bank_code"]) == (
        "0987654321",
        "SIMULATED ACCOUNT 4321",
        "057",
    )


async def test_forget_hides_the_note_at_once_and_undo_brings_it_back():
    stack = make_stack()
    note = await saved(stack, ALICE, **CITY)
    gone = await propose(stack, ALICE, "forget", id=note)
    assert gone["structuredContent"]["memory"]["state"] == "forgotten"
    assert (await stack.db.row("SELECT deleted_at FROM memory_entry"))["deleted_at"] is not None
    undone = await decide(stack, ALICE, gone, "undo_memory")
    assert undone["structuredContent"]["memory"]["state"] == "restored"
    assert (await stack.db.row("SELECT deleted_at FROM memory_entry"))["deleted_at"] is None
    again = await decide(stack, ALICE, gone, "undo_memory")
    assert again["structuredContent"]["memory"]["state"] == "restored"


async def test_undo_is_refused_when_the_retention_period_has_passed():
    stack = make_stack()
    note = await saved(stack, ALICE, **CITY)
    gone = await propose(stack, ALICE, "forget", id=note)
    stack.clock.advance(31 * 86_400)
    late = await decide(stack, ALICE, gone, "undo_memory")
    assert late["isError"] is True and text_of(late).startswith("MEMORY_GONE")


async def test_a_forget_cannot_be_confirmed_or_discarded_as_a_proposal():
    stack = make_stack()
    note = await saved(stack, ALICE, **CITY)
    gone = await propose(stack, ALICE, "forget", id=note)
    for tool in ("confirm_memory", "discard_memory"):
        assert text_of(await decide(stack, ALICE, gone, tool)).startswith("MEMORY_INVALID")


async def test_save_is_refused_when_the_owner_has_no_room_left():
    stack = make_stack(
        memory=__import__("checkout.memory.settings", fromlist=["x"]).MemorySettings(max_entries=2)
    )
    await saved(stack, ALICE, **USUAL)
    await saved(stack, ALICE, **CITY)
    full = await memory_call(stack, ALICE, "remember", kind="fact", title="Third", hook="x", body="y")
    assert text_of(full).startswith("MEMORY_FULL")


async def test_a_recipient_is_forgotten_and_brought_back_like_any_note():
    stack = make_stack()
    note = await saved(stack, ALICE, **MUM)
    gone = await propose(stack, ALICE, "forget", id=note)
    view = gone["structuredContent"]["memory"]
    assert (view["state"], view["kind"], view["title"], view["detail"]) == (
        "forgotten",
        "recipient",
        "Mum",
        "",
    )
    assert "0123456789" not in json.dumps(gone)
    back = await decide(stack, ALICE, gone, "undo_memory")
    assert back["structuredContent"]["memory"]["state"] == "restored"
    assert (await stack.db.row("SELECT account_number FROM memory_entry"))["account_number"] == "0123456789"
