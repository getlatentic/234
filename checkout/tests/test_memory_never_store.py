# SPDX-License-Identifier: AGPL-3.0-or-later
"""What memory never keeps is refused with a reason, before a proposal is made and again before a save."""

import pytest

from checkout.memory.never_store import refusal_reason
from tests.connector_support import text_of
from tests.keys import fake_key
from tests.memory_support import MUM, USUAL, decide, entry_count, memory_call, propose, saved
from tests.support import ALICE, make_stack

LUHN_VALID_UNBRANDED = "1234 5678 1234 5670"
REFUSED = [
    ("fact", "Card", "my card number is 4111 1111 1111 1111"),
    ("fact", "Card", "4111-1111-1111-1111"),
    ("fact", "Debit card", f"pay with {LUHN_VALID_UNBRANDED} always"),
    ("fact", "Amex", "378282246310005"),
    ("fact", "Old card", "4222222222222"),
    ("preference", "Card", "use 5555555555554444 for food"),
    ("fact", "Back of card", "the cvv is 123"),
    ("fact", "Card code", "CVC 456"),
    ("fact", "Bank", "my ATM PIN is 1234"),
    ("fact", "Bank", "pin: 0000"),
    ("fact", "Login", "the OTP they sent was 482913"),
    ("fact", "Login", "one-time code 482913"),
    ("fact", "Account", "my password is hunter2"),
    ("fact", "Account", "Passcode is open sesame"),
    ("fact", "Phone lock", "passphrase correct horse"),
    ("fact", "Security", "security code 99"),
    ("fact", "Identity", "my BVN is 22212345678"),
    ("fact", "Identity", "NIN 12345678901"),
    ("fact", "Identity", "bvn"),
    ("fact", "Identity", "I will not tell you my NIN"),
    ("fact", "Number", "12345678901"),
    ("fact", "Number", "0123456789012"),
    ("fact", "Number", "1234 5678 9012 3456 78"),
    ("preference", "Usual", "send to 0123456789"),
    ("fact", "Sister", "reach her on 07031234567"),
    ("fact", "About me", "my number is 07031234567"),
    ("preference", "Default", "network MTN, line 07031234567 and 08031234567 and 0123456789"),
    ("fact", "Key", f"my key is {fake_key('live')}"),
    ("fact", "Key", f"use {fake_key('test')} for tests"),
    ("fact", "Key", "AKIAIOSFODNN7EXAMPLE"),
    ("fact", "Key", "the api key is abc"),
    ("fact", "Key", "API-key abc"),
    ("fact", "Secret", "my secret key is mango"),
    ("fact", "Secret", "private key follows"),
    ("fact", "Token", "access token abc"),
    ("fact", "Token", "Bearer abc"),
    ("fact", "Token", "d41d8cd98f00b204e9800998ecf8427ed41d8cd98f00b204"),
    ("recipient", "Mum", "0123456789"),
    ("recipient", "Mum 0123456789", "x"),
    ("recipient", "Mum", "phone 07031234567"),
]
ALLOWED = [
    ("preference", "Usual airtime", "MTN, 500 naira"),
    ("fact", "Lives in", "Yaba, Lagos since 2019"),
    ("fact", "Phone number", "07031234567"),
    ("fact", "Mobile", "0703 123 4567"),
    ("preference", "Default airtime number", "+2347031234567 on MTN"),
    ("fact", "Birthday", "14 March 1990"),
    ("fact", "Budget", "spends ₦25,000 on data a month"),
    ("fact", "Reference", "order 1234567"),
    ("fact", "Pineapple", "likes pineapple rice"),
    ("fact", "Timing", "pays rent on the 1st, 10:30 am"),
    ("preference", "Language", "answers in Pidgin"),
]


CARDS = [body for kind, title, body in REFUSED if title in ("Card", "Debit card", "Amex", "Old card")]


@pytest.mark.parametrize("body", CARDS)
def test_a_card_number_is_refused_as_a_card_number(body):
    assert "card number" in refusal_reason("fact", "Card", "a note", body)


@pytest.mark.parametrize(("kind", "title", "body"), REFUSED)
def test_what_memory_never_keeps_is_refused(kind, title, body):
    assert refusal_reason(kind, title, "a note", body) is not None


@pytest.mark.parametrize(("kind", "title", "body"), ALLOWED)
def test_what_a_person_says_about_themselves_is_kept(kind, title, body):
    assert refusal_reason(kind, title, "a note", body) is None


def test_a_phone_number_is_kept_only_where_the_title_says_it_is_one():
    assert refusal_reason("fact", "Phone", "a note", "07031234567") is None
    assert refusal_reason("fact", "Sister", "a note", "07031234567") is not None


def test_a_long_number_is_refused_wherever_it_hides():
    assert refusal_reason("fact", "Phone", "call 12345678901234", "x") is not None
    assert refusal_reason("fact", "Phone", "x", "line one\n12345678901") is not None


@pytest.mark.parametrize("body", ["my cvv is 123", f"card {LUHN_VALID_UNBRANDED}", "my BVN is 22212345678"])
async def test_the_connector_refuses_to_propose_it_and_writes_nothing(body):
    stack = make_stack()
    refused = await memory_call(
        stack, ALICE, "remember", kind="fact", title="Secret", hook="a note", body=body
    )
    assert refused["isError"] is True
    assert text_of(refused).startswith(("MEMORY_REFUSED", "CARD_DATA_REFUSED"))
    assert await entry_count(stack) == 0 and await stack.count("memory_proposal") == 0


async def test_the_reason_is_plain_and_tells_the_model_to_say_why():
    stack = make_stack()
    refused = await memory_call(
        stack, ALICE, "remember", kind="fact", title="Bank", hook="a", body="PIN is 4321"
    )
    assert text_of(refused).startswith("MEMORY_REFUSED: That is about a PIN, a code, a password or a key.")
    assert "Tell the person why" in text_of(refused)


async def test_a_proposal_that_slipped_into_the_table_is_refused_again_at_save():
    stack = make_stack()
    proposed = await propose(stack, ALICE, "remember", kind="fact", title="Note", hook="a note", body="fine")
    await stack.db.execute("UPDATE memory_proposal SET payload = replace(payload, 'fine', 'my cvv is 123')")
    done = await memory_call(
        stack,
        ALICE,
        "confirm_memory",
        proposal_id=proposed["structuredContent"]["proposal_id"],
        confirm_token=proposed["_meta"]["confirmToken"],
    )
    assert text_of(done).startswith("MEMORY_REFUSED") and await entry_count(stack) == 0


async def test_a_recipients_account_number_must_be_ten_digits_and_never_sits_in_a_text():
    stack = make_stack()
    short = await memory_call(stack, ALICE, "remember", **{**MUM, "account_number": "12345"})
    assert text_of(short).startswith("INVALID_INPUT")
    digits = await memory_call(stack, ALICE, "remember", **{**MUM, "body": "account 0123456789"})
    assert text_of(digits).startswith("MEMORY_REFUSED")
    ok = await propose(stack, ALICE, "remember", **MUM)
    assert (await decide(stack, ALICE, ok))["structuredContent"]["memory"]["state"] == "saved"


async def test_a_change_to_a_note_is_checked_like_a_new_note():
    stack = make_stack()
    note = await saved(stack, ALICE, **USUAL)
    refused = await memory_call(stack, ALICE, "update", id=note, hook="the PIN is 4321")
    assert text_of(refused).startswith("MEMORY_REFUSED")
    refused = await memory_call(stack, ALICE, "update", id=note, body="my BVN is 22212345678")
    assert text_of(refused).startswith("MEMORY_REFUSED")


async def test_a_change_to_a_recipient_is_checked_too():
    stack = make_stack()
    mum = await saved(stack, ALICE, **MUM)
    refused = await memory_call(stack, ALICE, "update", id=mum, body="account 0123456789")
    assert text_of(refused).startswith("MEMORY_REFUSED")
    refused = await memory_call(stack, ALICE, "update", id=mum, title="Mum 0123456789")
    assert text_of(refused).startswith("MEMORY_REFUSED")
