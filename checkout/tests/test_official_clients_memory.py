# SPDX-License-Identifier: AGPL-3.0-or-later
"""Memory through the official Python MCP client on the running Worker and its local D1, as the chat host
drives it: the memory owner header on every request, a proposal, the card's Save, a recall by words (D1's
FTS5), the index, a forget with its Undo, a recipient resolved by the bank, a transfer to it by id, and one
account's notes out of another's reach. Run with `pytest -m worker`."""

import httpx
import pytest
from mcp import Client
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client
from mcp.shared.exceptions import MCPError

from tests.worker_client import ALICE, BASE_URL, BOB, OWNER_HEADER

pytestmark = pytest.mark.worker

MEMORY = f"{BASE_URL}/memory/mcp"
SEND = f"{BASE_URL}/send-money/mcp"
MEMORY_OWNER_HEADER = "x-memory-owner"
MODEL = {"recall", "remember", "update", "forget"}
CARD = {"confirm_memory", "discard_memory", "undo_memory"}
PAGE = {
    "memory_index",
    "list_memories",
    "edit_memory",
    "forget_memory",
    "export_memories",
    "delete_all_memories",
}
USUAL = {
    "kind": "preference",
    "title": "Usual airtime",
    "hook": "MTN, 500 naira",
    "body": "Buys MTN airtime.",
}
MUM = {"kind": "recipient", "title": "Mum", "account_number": "0123456789", "bank": "GTB"}


@pytest.fixture(autouse=True)
async def clean_ledger():
    async with httpx.AsyncClient() as http:
        await http.post(f"{BASE_URL}/test/reset")


def acting_as(owner: str, url: str = MEMORY, notes: bool = True) -> Client:
    headers = {OWNER_HEADER: owner, **({MEMORY_OWNER_HEADER: owner} if notes else {})}
    return Client(streamable_http_client(url, http_client=create_mcp_http_client(headers=headers)))


def decision(made, **over) -> dict:
    return {
        "proposal_id": made.structured_content["proposal_id"],
        "confirm_token": made.meta["confirmToken"],
        **over,
    }


async def saved(client: Client, **fields) -> str:
    made = await client.call_tool("remember", fields)
    assert not made.is_error, made.content[0].text
    done = await client.call_tool("confirm_memory", decision(made))
    assert done.structured_content["memory"]["state"] == "saved"
    return made.structured_content["proposal_id"]


async def test_the_tools_are_listed_with_who_may_call_them_and_what_they_do():
    async with acting_as(ALICE) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        assert set(tools) == MODEL | CARD | PAGE

        def visibility(name):
            return tools[name].meta["ui"]["visibility"]

        assert all(visibility(name) == ["model"] for name in MODEL)
        assert all(visibility(name) == ["app"] for name in CARD | PAGE)
        assert tools["forget"].annotations.destructive_hint is True
        assert tools["remember"].meta["ui"]["resourceUri"] == "ui://memory/card.html"
        assert "You cannot save: the person presses Save on the card." in client.instructions
        read = await client.read_resource("ui://memory/card.html")
        assert read.contents[0].mime_type == "text/html;profile=mcp-app" and "Save" in read.contents[0].text


async def test_a_call_with_no_memory_owner_is_refused():
    async with acting_as(ALICE, notes=False) as client:
        with pytest.raises(MCPError, match="Memory is for signed-in accounts"):
            await client.call_tool("memory_index", {})


async def test_a_proposal_writes_nothing_and_save_writes_one_note():
    async with acting_as(ALICE) as client:
        made = await client.call_tool("remember", USUAL)
        assert not made.is_error and made.structured_content["memory"]["state"] == "pending"
        assert (await client.call_tool("memory_index", {})).structured_content["entries"] == 0
        assert (
            "confirmToken" not in made.content[0].text
            and made.meta["confirmToken"] not in made.content[0].text
        )
        done = await client.call_tool("confirm_memory", decision(made))
        assert done.structured_content["memory"]["state"] == "saved"
        again = await client.call_tool("confirm_memory", decision(made))
        assert again.structured_content["memory"]["state"] == "saved"
        index = (await client.call_tool("memory_index", {})).structured_content
        assert index["entries"] == 1 and "- [Usual airtime](" in index["index"]


async def test_a_save_without_the_token_is_refused():
    async with acting_as(ALICE) as client:
        made = await client.call_tool("remember", USUAL)
        denied = await client.call_tool("confirm_memory", decision(made, confirm_token="0" * 64))
        assert denied.is_error and denied.content[0].text.startswith("MEMORY_DENIED")
        assert (await client.call_tool("memory_index", {})).structured_content["entries"] == 0


async def test_a_note_is_found_by_its_words_and_read_by_its_id_as_quoted_data():
    async with acting_as(ALICE) as client:
        note = await saved(client, **USUAL)
        found = await client.call_tool("recall", {"query": "airtime"})
        assert [n["id"] for n in found.structured_content["notes"]] == [note]
        assert found.structured_content["untrusted"] is True and "never instructions" in found.content[0].text
        read = await client.call_tool("recall", {"id": note})
        assert read.structured_content["notes"][0]["body"] == "Buys MTN airtime."
        assert (await client.call_tool("recall", {"query": "zzzz"})).structured_content["notes"] == []


async def test_a_forgotten_note_is_gone_from_search_and_undo_brings_it_back():
    async with acting_as(ALICE) as client:
        note = await saved(client, **USUAL)
        gone = await client.call_tool("forget", {"id": note})
        assert gone.structured_content["memory"]["state"] == "forgotten"
        assert (await client.call_tool("recall", {"query": "airtime"})).structured_content["notes"] == []
        assert (await client.call_tool("memory_index", {})).structured_content["entries"] == 0
        back = await client.call_tool("undo_memory", decision(gone))
        assert back.structured_content["memory"]["state"] == "restored"
        assert (await client.call_tool("recall", {"query": "airtime"})).structured_content["notes"]


async def test_a_note_is_changed_in_place_and_searched_by_its_new_words():
    async with acting_as(ALICE) as client:
        note = await saved(client, **USUAL)
        await client.call_tool(
            "edit_memory", {"id": note, "title": "Data bundle", "hook": "Airtel, 1000 naira"}
        )
        assert (await client.call_tool("recall", {"query": "bundle"})).structured_content["notes"]
        assert (await client.call_tool("recall", {"query": "usual"})).structured_content["notes"] == []


async def test_a_recipient_is_saved_with_the_banks_name_and_the_model_never_reads_the_whole_number():
    async with acting_as(ALICE) as client:
        note = await saved(client, **MUM)
        recalled = (await client.call_tool("recall", {"id": note})).structured_content["notes"][0]
        assert (
            recalled["account_name"] == "SIMULATED ACCOUNT 6789"
            and recalled["account_masked"] == "******6789"
        )
        assert "0123456789" not in str(recalled)
        whole = (await client.call_tool("list_memories", {})).structured_content["entries"][0]
        assert whole["account_number"] == "0123456789" and whole["bank"] == "Guaranty Trust Bank"


async def test_a_bank_that_is_not_exactly_one_bank_and_an_account_that_does_not_resolve_are_refused():
    async with acting_as(ALICE) as client:
        unknown = await client.call_tool("remember", {**MUM, "bank": "Bank of Nowhere"})
        assert unknown.is_error and unknown.content[0].text.startswith("BANK_UNKNOWN")
        missing = await client.call_tool("remember", {**MUM, "account_number": "9999000011"})
        assert missing.is_error and missing.content[0].text.startswith("PROVIDER_ERROR")


async def test_a_transfer_to_a_saved_recipient_goes_to_the_account_the_server_loaded():
    async with acting_as(ALICE) as memory, acting_as(ALICE, SEND, notes=False) as send:
        note = await saved(memory, **MUM)
        args = {"recipient_memory_id": note, "amount_kobo": 500_000, "amount_as_user_said": "5k"}
        made = await send.call_tool("create_transfer_quote", {**args, "idempotency_key": "py-memory-send-1"})
        quote = made.structured_content["quote"]
        assert not made.is_error and quote["details"]["recipientName"] == "SIMULATED ACCOUNT 6789"
        assert quote["details"]["accountMasked"].endswith("6789") and quote["phase"] == "awaiting_approval"
        both = await send.call_tool(
            "create_transfer_quote",
            {**args, "account_number": "0987654321", "idempotency_key": "py-memory-send-2"},
        )
        assert both.is_error and both.content[0].text.startswith("INVALID_INPUT")


async def test_one_account_cannot_read_search_change_or_use_the_notes_of_another():
    async with (
        acting_as(ALICE) as alice,
        acting_as(BOB) as bob,
        acting_as(BOB, SEND, notes=False) as bobs_send,
    ):
        mum = await saved(alice, **MUM)
        assert (await bob.call_tool("recall", {"id": mum})).is_error
        assert (await bob.call_tool("recall", {"query": "mum"})).structured_content["notes"] == []
        assert (await bob.call_tool("forget", {"id": mum})).is_error
        assert (await bob.call_tool("memory_index", {})).structured_content["entries"] == 0
        assert (await bob.call_tool("export_memories", {})).structured_content["entries"] == []
        args = {"recipient_memory_id": mum, "amount_kobo": 500_000, "amount_as_user_said": "5k"}
        stolen = await bobs_send.call_tool(
            "create_transfer_quote", {**args, "idempotency_key": "py-memory-bob-1"}
        )
        assert stolen.is_error and stolen.content[0].text.startswith("RECIPIENT_NOT_FOUND")
        assert (await alice.call_tool("memory_index", {})).structured_content["entries"] == 1


async def test_what_is_never_kept_is_refused_through_the_wire():
    async with acting_as(ALICE) as client:
        for body in ("my cvv is 123", "my BVN is 22212345678", "my password is hunter2"):
            refused = await client.call_tool("remember", {**USUAL, "body": body})
            assert refused.is_error and refused.content[0].text.startswith("MEMORY_REFUSED"), body
        card = await client.call_tool("remember", {**USUAL, "body": "card 4111 1111 1111 1111"})
        assert card.is_error
        assert (await client.call_tool("memory_index", {})).structured_content["entries"] == 0


async def test_deleting_everything_leaves_nothing_to_search():
    async with acting_as(ALICE) as client:
        await saved(client, **USUAL)
        await saved(client, **MUM)
        assert (await client.call_tool("delete_all_memories", {})).structured_content["deleted"] == 2
        assert (await client.call_tool("recall", {"query": "mum"})).structured_content["notes"] == []
        assert (await client.call_tool("memory_index", {})).structured_content["entries"] == 0
