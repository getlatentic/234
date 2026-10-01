# SPDX-License-Identifier: AGPL-3.0-or-later
"""A transfer to a saved recipient: the model names the recipient by id, and the server loads the account and
the bank from the owner's own notes, asks the bank for the name again, and refuses what does not add up."""

import json

import pytest

from checkout.errors import DomainError
from checkout.owner import acting_for
from tests.connector_support import key, quote_of, text_of
from tests.memory_support import MUM, answered, bank_answers, decide, memory_call, propose, saved
from tests.support import ALICE, BOB, PaystackOverride, make_stack

SEND = "send-money"


def transfer(**over):
    return {
        "amount_kobo": 500_000,
        "amount_as_user_said": "5k",
        "idempotency_key": key("saved"),
        **over,
    }


async def send(stack, owner, **over):
    return await stack.call_as(owner, SEND, "create_transfer_quote", **transfer(**over))


async def held_details(stack) -> dict:
    """What the ledger holds of the only quote: the whole account, which no card or model result carries."""
    return json.loads((await stack.rows("SELECT details FROM quotes"))[0]["details"])


async def test_the_quote_goes_to_the_account_and_bank_loaded_from_the_note():
    stack = make_stack()
    mum = await saved(stack, ALICE, **MUM)
    made = await send(stack, ALICE, recipient_memory_id=mum)
    details = await held_details(stack)
    assert (details["accountNumber"], details["bankCode"]) == ("0123456789", "058")
    assert quote_of(made)["amount"]["kobo"] == 500_000
    assert quote_of(made)["merchant"] == "SIMULATED ACCOUNT 6789"


async def test_the_model_cannot_give_digits_for_a_saved_recipient():
    stack = make_stack()
    mum = await saved(stack, ALICE, **MUM)
    for extra in ({"account_number": "0987654321"}, {"bank": "GTB"}, {"bank_code": "058"}):
        refused = await send(stack, ALICE, recipient_memory_id=mum, **extra)
        assert refused["isError"] is True and text_of(refused).startswith("INVALID_INPUT")
        assert "alone" in text_of(refused)
    assert await stack.count("quotes") == 0


async def test_a_transfer_names_a_recipient_or_an_account_and_nothing_else_is_a_quote():
    stack = make_stack()
    nobody = await send(stack, ALICE)
    assert text_of(nobody).startswith("INVALID_INPUT") and "recipient_memory_id" in text_of(nobody)
    plain = await send(stack, ALICE, account_number="0123456789", bank="GTB")
    assert quote_of(plain)["details"]["accountMasked"].endswith("6789")


async def test_another_owners_recipient_is_not_found_and_looks_like_one_that_does_not_exist():
    stack = make_stack()
    mum = await saved(stack, ALICE, **MUM)
    theirs = await send(stack, BOB, recipient_memory_id=mum)
    nothing = await send(stack, BOB, recipient_memory_id="0" * 16)
    assert text_of(theirs).startswith("RECIPIENT_NOT_FOUND") and text_of(theirs) == text_of(nothing)
    assert await stack.count("quotes") == 0


async def test_a_note_that_is_not_a_recipient_is_refused():
    stack = make_stack()
    usual = await saved(stack, ALICE, kind="fact", title="Place", hook="Yaba", body="Lives in Yaba")
    refused = await send(stack, ALICE, recipient_memory_id=usual)
    assert text_of(refused).startswith("RECIPIENT_NOT_FOUND")


async def test_a_forgotten_recipient_is_not_found():
    stack = make_stack()
    mum = await saved(stack, ALICE, **MUM)
    await memory_call(stack, ALICE, "forget", id=mum)
    assert text_of(await send(stack, ALICE, recipient_memory_id=mum)).startswith("RECIPIENT_NOT_FOUND")


async def test_the_quote_is_refused_when_the_bank_now_gives_another_name():
    stack = make_stack()
    mum = await saved(stack, ALICE, **MUM)
    paystack = stack.app.contexts[SEND].paystack
    stack.override(
        SEND, paystack=PaystackOverride(paystack, resolve_account=lambda lookup: answered("SOMEONE ELSE"))
    )
    with acting_for(ALICE), pytest.raises(DomainError) as refused:
        await stack.transfers.create_quote(**transfer(recipient_memory_id=mum, narration=None))
    message = str(refused.value)
    assert refused.value.code == "RECIPIENT_NAME_CHANGED"
    assert '"SOMEONE ELSE"' in message and "SIMULATED ACCOUNT 6789" in message
    assert "Nothing was quoted" in message and await stack.count("quotes") == 0
    assert any("recipient.name_changed" in line for line in stack.audit_lines)


async def test_the_recipient_becomes_the_most_recently_used_note():
    stack = make_stack()
    mum = await saved(stack, ALICE, **MUM)
    dad = await saved(stack, ALICE, **{**MUM, "title": "Dad"})
    stack.clock.advance(60)
    await send(stack, ALICE, recipient_memory_id=mum)
    index = (await memory_call(stack, ALICE, "memory_index"))["structuredContent"]["index"]
    lines = [line for line in index.splitlines() if line.startswith("- [")]
    assert lines[0].startswith("- [Mum]") and lines[1].startswith("- [Dad]") and dad


async def test_the_same_request_again_is_the_same_quote():
    stack = make_stack()
    mum = await saved(stack, ALICE, **MUM)
    sent = transfer(recipient_memory_id=mum)
    first = await stack.call_as(ALICE, SEND, "create_transfer_quote", **sent)
    second = await stack.call_as(ALICE, SEND, "create_transfer_quote", **sent)
    assert quote_of(first)["id"] == quote_of(second)["id"]


async def test_the_approval_card_shows_the_banks_name_and_the_masked_number():
    stack = make_stack()
    mum = await saved(stack, ALICE, **MUM)
    quote = quote_of(await send(stack, ALICE, recipient_memory_id=mum))
    assert quote["details"]["recipientName"] == "SIMULATED ACCOUNT 6789"
    assert (
        quote["details"]["accountMasked"].endswith("6789")
        and "0123456789" not in quote["details"]["accountMasked"]
    )


async def test_memory_never_approves_or_sends_anything():
    stack = make_stack()
    mum = await saved(stack, ALICE, **MUM)
    made = await send(stack, ALICE, recipient_memory_id=mum)
    assert quote_of(made)["phase"] == "awaiting_approval"
    assert await stack.count("quote_events") == 0


async def test_a_recipient_saved_with_another_bank_answer_is_used_with_that_answer():
    stack = make_stack()
    bank_answers(stack, lambda lookup: answered("ADA OKAFOR"))
    proposed = await propose(stack, ALICE, "remember", **MUM)
    await decide(stack, ALICE, proposed)
    mum = proposed["structuredContent"]["proposal_id"]
    refused = await send(stack, ALICE, recipient_memory_id=mum)
    assert text_of(refused).startswith("RECIPIENT_NAME_CHANGED")
