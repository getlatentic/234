# SPDX-License-Identifier: AGPL-3.0-or-later
"""Through the connector's HTTP surface, as the host calls it: one owner can never read, change, forget,
restore, export or even count another's notes, and a call with no memory owner reaches none."""

import json

import pytest

from checkout.owner import MEMORY_OWNER_HEADER
from tests.connector_support import text_of
from tests.memory_support import CITY, MUM, USUAL, decide, entry_count, memory_call, propose, saved
from tests.support import ALICE, BOB, make_stack


async def two_owners():
    stack = make_stack()
    mum = await saved(stack, ALICE, **MUM)
    usual = await saved(stack, ALICE, **USUAL)
    return stack, mum, usual


async def test_another_owner_cannot_recall_a_note_by_its_id():
    stack, mum, _ = await two_owners()
    seen = await memory_call(stack, BOB, "recall", id=mum)
    assert seen["isError"] is True and text_of(seen).startswith("MEMORY_NOT_FOUND")
    assert "Mum" not in json.dumps(seen) and "structuredContent" not in seen


async def test_another_owners_id_looks_exactly_like_an_id_that_does_not_exist():
    stack, mum, _ = await two_owners()
    theirs = text_of(await memory_call(stack, BOB, "recall", id=mum))
    nothing = text_of(await memory_call(stack, BOB, "recall", id="0" * 16))
    assert theirs == nothing


async def test_a_search_finds_only_the_owners_own_notes():
    stack, _, _ = await two_owners()
    await saved(
        stack, BOB, **{**CITY, "title": "Mum lives here", "hook": "Mum's house", "body": "Mum, Surulere"}
    )
    mine = (await memory_call(stack, ALICE, "recall", query="mum"))["structuredContent"]["notes"]
    theirs = (await memory_call(stack, BOB, "recall", query="mum"))["structuredContent"]["notes"]
    assert [n["title"] for n in mine] == ["Mum"] and [n["title"] for n in theirs] == ["Mum lives here"]


async def test_another_owner_cannot_forget_change_or_restore_a_note():
    stack, mum, usual = await two_owners()
    for tool, args in (("forget", {"id": mum}), ("update", {"id": usual, "hook": "Hacked"})):
        refused = await memory_call(stack, BOB, tool, **args)
        assert text_of(refused).startswith("MEMORY_NOT_FOUND")
    assert await entry_count(stack, ALICE) == 2
    forgotten = await propose(stack, ALICE, "forget", id=usual)
    stolen = await decide(stack, BOB, forgotten, "undo_memory")
    assert text_of(stolen).startswith("MEMORY_DENIED")
    assert (await stack.db.row("SELECT deleted_at FROM memory_entry WHERE id = ?", usual))["deleted_at"]


async def test_another_owner_cannot_edit_or_delete_from_the_page_list():
    stack, mum, _ = await two_owners()
    assert text_of(await memory_call(stack, BOB, "edit_memory", id=mum, title="Mine")).startswith(
        "MEMORY_NOT_FOUND"
    )
    assert text_of(await memory_call(stack, BOB, "forget_memory", id=mum)).startswith("MEMORY_NOT_FOUND")
    assert (await memory_call(stack, BOB, "list_memories"))["structuredContent"]["entries"] == []
    assert (await memory_call(stack, BOB, "export_memories"))["structuredContent"]["entries"] == []


async def test_deleting_everything_deletes_only_the_callers_notes():
    stack, _, _ = await two_owners()
    await saved(stack, BOB, **CITY)
    done = await memory_call(stack, BOB, "delete_all_memories")
    assert done["structuredContent"]["deleted"] == 1
    assert await entry_count(stack, ALICE) == 2 and await entry_count(stack, BOB) == 0


async def test_the_index_and_the_count_of_one_owner_say_nothing_of_another():
    stack, _, _ = await two_owners()
    empty = (await memory_call(stack, BOB, "memory_index"))["structuredContent"]
    assert empty == {"index": "", "entries": 0, "tokens": 0}


async def test_a_proposal_of_one_owner_is_not_found_by_another_even_with_its_token():
    stack = make_stack()
    proposed = await propose(stack, ALICE, "remember", **USUAL)
    pid, token = proposed["structuredContent"]["proposal_id"], proposed["_meta"]["confirmToken"]
    for tool in ("confirm_memory", "discard_memory", "undo_memory"):
        denied = await memory_call(stack, BOB, tool, proposal_id=pid, confirm_token=token)
        assert denied["isError"] is True and "Usual airtime" not in json.dumps(denied)


async def test_a_call_with_no_memory_owner_is_refused_for_every_tool_and_reaches_nothing():
    stack, mum, _ = await two_owners()
    for tool, args in (
        ("recall", {"query": "mum"}),
        ("remember", {**USUAL}),
        ("forget", {"id": mum}),
        ("memory_index", {}),
        ("list_memories", {}),
        ("export_memories", {}),
    ):
        body = {"name": tool, "arguments": args}
        answer = await stack.mcp("memory", "tools/call", body, ALICE)
        assert answer["error"]["message"] == "Memory is for signed-in accounts."
    assert await entry_count(stack, ALICE) == 2


async def test_the_ledger_owner_alone_does_not_open_memory():
    stack, _, _ = await two_owners()
    answer = await stack.mcp("memory", "tools/call", {"name": "list_memories", "arguments": {}}, ALICE)
    assert "result" not in answer


async def test_the_memory_owner_is_read_from_its_header_and_from_nowhere_else():
    stack, _, _ = await two_owners()
    sly = {
        "name": "list_memories",
        "arguments": {"owner": BOB},
        "_meta": {"owner": ALICE, "memory_owner": ALICE},
    }
    answer = await stack.mcp("memory", "tools/call", sly, headers={MEMORY_OWNER_HEADER: BOB})
    assert answer["result"]["isError"] is True or answer["result"]["structuredContent"]["entries"] == []


@pytest.mark.parametrize("bad", ["", "ALICE", "a1" * 15, "zz" * 16, "a1" * 17])
async def test_a_memory_owner_that_is_not_an_owner_key_is_refused(bad):
    stack = make_stack()
    answer = await stack.mcp(
        "memory", "tools/call", {"name": "list_memories", "arguments": {}}, headers={MEMORY_OWNER_HEADER: bad}
    )
    assert answer["error"]["message"] == "The memory owner header is not an owner key."
