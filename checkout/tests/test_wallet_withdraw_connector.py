# SPDX-License-Identifier: AGPL-3.0-or-later
"""Withdrawing through the wallet connector, as the host relays the wallet card's calls: accounts only, the
model offered no tool that moves money, the token only in `_meta`, the account number never whole in what
the card or a model reads, and the history in plain words."""

import json

from tests.connector_support import listed, text_of, visibility
from tests.support import ALICE, BOB
from tests.wallet_card_support import CARD_ID, ok, wallet
from tests.withdrawal_support import ACCOUNT, NAME, funded

START = {"card_id": CARD_ID, "amount_naira": 20_000, "bank": "GTBank", "account_number": ACCOUNT}


async def start(stack, owner=ALICE, account=True):
    return await wallet(stack, "start_withdrawal", owner, account, **START)


def withdraw_args(started: dict, **over) -> dict:
    view = started["structuredContent"]["withdrawal"]
    return {
        "card_id": CARD_ID,
        "withdrawal_id": view["id"],
        "withdrawal_token": started["_meta"]["withdrawalToken"],
        "displayed_amount_kobo": view["amountKobo"],
        "confirmed_name": view["accountName"],
        **over,
    }


async def test_the_model_is_offered_no_withdrawal_tool(stack):
    tools = await listed(stack, "wallet")
    assert visibility(tools["start_withdrawal"]) == ["app"] and visibility(tools["withdraw"]) == ["app"]


async def test_a_visitor_can_neither_start_nor_approve_one(stack):
    for tool, args in (("start_withdrawal", START), ("withdraw", {"card_id": CARD_ID})):
        refused = await wallet(stack, tool, account=False, **args)
        assert refused["error"]["message"] == "Wallet is for signed-in accounts."
    assert await stack.count("wallet_withdrawal") == 0


async def test_start_shows_the_banks_name_and_keeps_the_token_out_of_sight(stack):
    await funded(stack)
    started = ok(await start(stack))
    view = started["structuredContent"]["withdrawal"]
    assert (view["accountName"], view["accountMasked"], view["amount"]) == (NAME, "******6789", "₦20,000")
    assert text_of(started) == f"Confirm the name: {NAME}."
    seen = json.dumps({k: started[k] for k in ("content", "structuredContent")})
    assert started["_meta"]["withdrawalToken"] not in seen and ACCOUNT not in seen


async def test_withdraw_on_the_card_pays_and_says_so_in_plain_words(stack):
    await funded(stack)
    done = ok(await wallet(stack, "withdraw", **withdraw_args(ok(await start(stack)))))
    data = done["structuredContent"]
    assert text_of(done) == f"Withdrawn: ₦20,000 to {NAME}, Guaranty Trust Bank."
    assert data["wallet"]["balance"] == "₦80,000"
    assert [(e["label"], e["amount"]) for e in data["wallet"]["entries"]] == [
        ("Withdrawn", "-₦20,000"),
        ("Added", "+₦100,000"),
    ]


async def test_the_card_reads_its_withdrawal_back(stack):
    await funded(stack)
    started = ok(await start(stack))
    withdrawal_id = started["structuredContent"]["withdrawal"]["id"]
    seen = ok(await wallet(stack, "wallet_view", card_id=CARD_ID, withdrawal_id=withdrawal_id))
    assert seen["structuredContent"]["withdrawal"]["state"] == "open"
    other = ok(await wallet(stack, "wallet_view", owner=BOB, card_id=CARD_ID, withdrawal_id=withdrawal_id))
    assert "withdrawal" not in other["structuredContent"]


async def test_a_name_the_card_did_not_show_withdraws_nothing(stack):
    await funded(stack)
    refused = await wallet(stack, "withdraw", **withdraw_args(ok(await start(stack)), confirmed_name="ME"))
    assert refused["isError"] and text_of(refused).startswith("NAME_NOT_CONFIRMED")
    assert await stack.count("sim_transfers") == 0
