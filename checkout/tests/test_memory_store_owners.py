# SPDX-License-Identifier: AGPL-3.0-or-later
"""Under the connector: every method of the store and of the proposals names its owner, so one owner's rows
are out of reach of another's calls however the caller got hold of an id."""

from checkout.memory.proposals import REMEMBER
from tests.memory_support import CITY, MUM, USUAL, memory_of, propose, saved
from tests.support import ALICE, BOB, make_stack

DAY = 86_400


async def alice_with_a_note():
    stack = make_stack()
    note = await saved(stack, ALICE, **USUAL)
    return stack, memory_of(stack), note


async def test_the_store_reads_nothing_of_another_owner():
    _, memory, note = await alice_with_a_note()
    store = memory.store
    assert await store.get(BOB, note) is None and await store.live(BOB) == []
    assert await store.index_rows(BOB) == [] and await store.count_live(BOB) == 0
    assert await store.search(BOB, "airtime") == []
    assert await store.title_taken(BOB, "preference", "Usual airtime") is None
    assert await store.title_taken(ALICE, "preference", "Usual airtime") == note


async def test_the_store_changes_nothing_of_another_owner():
    stack, memory, note = await alice_with_a_note()
    store = memory.store
    before = await stack.db.row("SELECT * FROM memory_entry WHERE id = ?", note)
    stack.clock.advance(60)
    await store.touch(BOB, note)
    assert await store.forget(BOB, note) == 0
    assert await store.edit(BOB, note, "Hacked", "Hacked") == 0
    assert await stack.db.row("SELECT * FROM memory_entry WHERE id = ?", note) == before


async def test_delete_everything_by_one_owner_leaves_the_other_owners_notes_and_proposals():
    stack, memory, note = await alice_with_a_note()
    await propose(stack, ALICE, "remember", **CITY)
    assert await memory.store.delete_everything(BOB) == 0
    assert await stack.count("memory_entry") == 1 and await stack.count("memory_proposal") == 2
    assert await memory.store.delete_everything(ALICE) == 1
    assert await stack.count("memory_proposal") == 0 and note


async def test_a_proposal_is_found_decided_and_applied_only_by_its_owner():
    stack = make_stack()
    memory = memory_of(stack)
    made = await propose(stack, ALICE, "remember", **CITY)
    pid = made["structuredContent"]["proposal_id"]
    proposal = await memory.proposals.get(ALICE, pid)
    assert await memory.proposals.get(BOB, pid) is None
    assert await memory.proposals.apply(BOB, proposal) is False and await stack.count("memory_entry") == 0
    assert await memory.proposals.discard(BOB, pid) is False
    assert (await memory.proposals.get(ALICE, pid)).state == "pending"
    assert await memory.proposals.apply(ALICE, proposal) is True and await stack.count("memory_entry") == 1


async def test_an_update_applied_by_another_owner_changes_nothing():
    stack = make_stack()
    memory = memory_of(stack)
    note = await saved(stack, ALICE, **USUAL)
    made = await propose(stack, ALICE, "update", id=note, hook="Airtel, 1000 naira")
    proposal = await memory.proposals.get(ALICE, made["structuredContent"]["proposal_id"])
    assert await memory.proposals.apply(BOB, proposal) is False
    assert (await stack.db.row("SELECT hook FROM memory_entry"))["hook"] == "MTN, 500 naira"


async def test_an_undo_by_another_owner_restores_nothing():
    stack, memory, note = await alice_with_a_note()
    gone = await propose(stack, ALICE, "forget", id=note)
    proposal = await memory.proposals.get(ALICE, gone["structuredContent"]["proposal_id"])
    assert await memory.proposals.undo_forget(BOB, proposal) is False
    assert (await stack.db.row("SELECT deleted_at FROM memory_entry"))["deleted_at"] is not None
    assert (await memory.proposals.get(ALICE, proposal.id)).state == "applied"


async def test_one_owners_pile_of_proposals_does_not_discard_another_owners():
    stack = make_stack()
    bobs = await propose(stack, BOB, "remember", **CITY)
    for number in range(12):
        stack.clock.advance(1)
        await propose(stack, ALICE, "remember", **{**CITY, "title": f"Place {number}"})
    assert (
        await memory_of(stack).proposals.get(BOB, bobs["structuredContent"]["proposal_id"])
    ).state == "pending"


async def test_a_proposal_that_is_not_pending_is_not_applied_whoever_asks():
    stack = make_stack()
    memory = memory_of(stack)
    made = await propose(stack, ALICE, "remember", **CITY)
    pid = made["structuredContent"]["proposal_id"]
    pending = await memory.proposals.get(ALICE, pid)
    assert await memory.proposals.discard(ALICE, pid) is True
    assert await memory.proposals.apply(ALICE, pending) is False and await stack.count("memory_entry") == 0
    assert pending.op == REMEMBER


async def test_a_proposal_that_has_expired_is_not_applied():
    stack = make_stack()
    memory = memory_of(stack)
    made = await propose(stack, ALICE, "remember", **CITY)
    pending = await memory.proposals.get(ALICE, made["structuredContent"]["proposal_id"])
    stack.clock.advance(DAY + 1)
    assert await memory.proposals.apply(ALICE, pending) is False and await stack.count("memory_entry") == 0


async def test_a_second_apply_of_the_same_proposal_writes_nothing_more():
    stack = make_stack()
    memory = memory_of(stack)
    made = await propose(stack, ALICE, "remember", **MUM)
    pending = await memory.proposals.get(ALICE, made["structuredContent"]["proposal_id"])
    assert await memory.proposals.apply(ALICE, pending) is True
    assert await memory.proposals.apply(ALICE, pending) is False and await stack.count("memory_entry") == 1


async def test_the_purge_leaves_the_live_notes_of_every_owner():
    stack = make_stack()
    await saved(stack, ALICE, **USUAL)
    await saved(stack, BOB, **CITY)
    stack.clock.advance(90 * DAY)
    await memory_of(stack).store.purge()
    assert await stack.count("memory_entry") == 2
