# SPDX-License-Identifier: AGPL-3.0-or-later
"""A saved recipient is what the bank says: the bank is exactly one bank, the name is the bank's answer, the
model is never given the whole account number, and a change of name stops a save."""

import json

from checkout.paystack.api import PaystackError
from tests.connector_support import text_of
from tests.memory_support import MUM, answered, bank_answers, decide, entry_count, memory_call, propose, saved
from tests.support import ALICE, make_stack


async def test_the_saved_name_is_the_banks_answer_never_the_models():
    stack = make_stack()
    bank_answers(stack, lambda lookup: answered("ADA OKAFOR"))
    proposed = await propose(
        stack, ALICE, "remember", **{**MUM, "title": "Mum", "body": "Her name is Grace Obi"}
    )
    assert (
        proposed["structuredContent"]["memory"]["detail"] == "ADA OKAFOR · Guaranty Trust Bank · ending 6789"
    )
    await decide(stack, ALICE, proposed)
    row = await stack.db.row("SELECT * FROM memory_entry")
    assert row["account_name"] == "ADA OKAFOR" and "ADA OKAFOR" in row["hook"]
    assert (row["bank_code"], row["account_number"], row["source"]) == ("058", "0123456789", "card")
    assert row["verified_at"] == stack.clock.now()


async def test_a_bank_that_fits_more_than_one_is_refused_and_nothing_is_proposed():
    stack = make_stack()
    refused = await memory_call(stack, ALICE, "remember", **{**MUM, "bank": "First"})
    assert text_of(refused).startswith(("BANK_AMBIGUOUS", "BANK_UNKNOWN"))
    nothing = await memory_call(stack, ALICE, "remember", **{**MUM, "bank": "Bank of Nowhere"})
    assert text_of(nothing).startswith("BANK_UNKNOWN")
    assert await stack.count("memory_proposal") == 0 and await entry_count(stack) == 0


async def test_an_account_that_does_not_resolve_is_refused():
    stack = make_stack()
    refused = await memory_call(stack, ALICE, "remember", **{**MUM, "account_number": "9999000011"})
    assert refused["isError"] is True and text_of(refused).startswith("PROVIDER_ERROR")
    assert await stack.count("memory_proposal") == 0


async def test_a_recipient_needs_an_account_and_a_bank():
    stack = make_stack()
    for missing in ("account_number", "bank"):
        args = {k: v for k, v in MUM.items() if k != missing}
        refused = await memory_call(stack, ALICE, "remember", **args)
        assert text_of(refused).startswith("MEMORY_INVALID") and "account_number and bank" in text_of(refused)


async def test_a_preference_or_a_fact_cannot_carry_an_account():
    stack = make_stack()
    refused = await memory_call(
        stack, ALICE, "remember", kind="fact", title="Place", hook="h", body="b", account_number="0123456789"
    )
    assert text_of(refused).startswith("MEMORY_INVALID")


async def test_the_model_never_sees_a_whole_account_number_in_any_result():
    stack = make_stack()
    note = await saved(stack, ALICE, **MUM)
    proposed = await propose(stack, ALICE, "remember", **{**MUM, "title": "Dad"})
    shown = [
        await memory_call(stack, ALICE, "recall", id=note),
        await memory_call(stack, ALICE, "recall", query="mum"),
        proposed,
        await memory_call(stack, ALICE, "memory_index"),
    ]
    for result in shown:
        assert "0123456789" not in json.dumps({k: v for k, v in result.items() if k != "_meta"})
    recalled = (await memory_call(stack, ALICE, "recall", id=note))["structuredContent"]["notes"][0]
    assert recalled["account_masked"] == "******6789" and recalled["bank"] == "Guaranty Trust Bank"


async def test_the_page_list_and_the_export_hold_the_whole_entry_for_its_owner():
    stack = make_stack()
    await saved(stack, ALICE, **MUM)
    listed = (await memory_call(stack, ALICE, "list_memories"))["structuredContent"]["entries"][0]
    exported = (await memory_call(stack, ALICE, "export_memories"))["structuredContent"]["entries"][0]
    assert listed["account_number"] == "0123456789" == exported["account_number"]
    assert exported["account_name"] == "SIMULATED ACCOUNT 6789" and exported["verified_at"]


async def test_a_save_is_refused_when_the_bank_now_gives_another_name():
    stack = make_stack()
    answers = iter(["ADA OKAFOR", "SOMEONE ELSE"])
    bank_answers(stack, lambda lookup: answered(next(answers)))
    proposed = await propose(stack, ALICE, "remember", **MUM)
    done = await decide(stack, ALICE, proposed)
    assert done["structuredContent"]["memory"]["state"] == "refused"
    assert "different name" in done["structuredContent"]["memory"]["note"]
    assert await entry_count(stack) == 0
    again = await decide(stack, ALICE, proposed)
    assert again["structuredContent"]["memory"]["state"] == "discarded"


async def test_a_save_is_refused_when_the_bank_cannot_be_asked():
    stack = make_stack()
    answers = [True]

    async def resolve(lookup):
        if answers:
            answers.clear()
            return "ADA OKAFOR"
        raise PaystackError("timeout", retryable=True)

    bank_answers(stack, resolve)
    proposed = await propose(stack, ALICE, "remember", **MUM)
    done = await decide(stack, ALICE, proposed)
    assert done["isError"] is True and text_of(done).startswith("PROVIDER_ERROR")
    assert await entry_count(stack) == 0
    retried = await decide(stack, ALICE, proposed)
    assert retried["isError"] is True


async def test_names_in_another_order_are_the_same_name():
    stack = make_stack()
    answers = iter(["ADA OKAFOR", "okafor  ada"])
    bank_answers(stack, lambda lookup: answered(next(answers)))
    proposed = await propose(stack, ALICE, "remember", **MUM)
    assert (await decide(stack, ALICE, proposed))["structuredContent"]["memory"]["state"] == "saved"


async def test_two_nicknames_for_one_account_are_two_notes():
    stack = make_stack()
    await saved(stack, ALICE, **MUM)
    await saved(stack, ALICE, **{**MUM, "title": "Mummy"})
    assert await entry_count(stack) == 2


def test_a_memory_id_is_never_digits_alone(monkeypatch):
    """An all-digit id starting like a card and passing Luhn would have the card guard withhold its result."""
    from checkout import ids
    from checkout.card_guard import contains_card_number

    assert contains_card_number('"id": "4111111111111111"')
    draws = iter(["4111111111111111", "4111a11111111111"])
    monkeypatch.setattr(ids.secrets, "token_hex", lambda n: next(draws))
    assert ids.new_memory_id() == "4111a11111111111"
