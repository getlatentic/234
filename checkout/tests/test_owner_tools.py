# SPDX-License-Identifier: AGPL-3.0-or-later
"""Through the connectors' HTTP surface, as the chat host calls it: the owner comes from the host's header
alone, and one owner's quotes, approvals, receipts and checkouts are out of reach of another's calls."""

import json

import pytest

from checkout.http import handle
from checkout.owner import DEFAULT_OWNER, OWNER_HEADER
from tests.connector_support import approve_args, key, quote_of, text_of
from tests.support import ALICE, BOB, make_stack

PAY = "paystack-pay"


def args(**over):
    return {
        "amount_kobo": 500_000,
        "amount_as_user_said": "5k",
        "description": "Lunch",
        "merchant": "Demo Kitchen",
        "idempotency_key": key("owner-tools"),
        **over,
    }


async def made_by(stack, owner, **over):
    return await stack.call_as(owner, PAY, "create_payment_quote", **args(**over))


async def state_of(stack, quote_id: str) -> str:
    return (await stack.rows("SELECT state FROM quotes WHERE id = ?", quote_id))[0]["state"]


class TestAnotherOwnersQuote:
    async def test_cannot_be_read_by_its_status_or_verified(self):
        stack = make_stack()
        alices = await made_by(stack, ALICE)
        for tool in ("get_quote_status", "verify_quote"):
            seen = await stack.call_as(BOB, PAY, tool, quote_id=quote_of(alices)["id"])
            assert seen["isError"] is True and text_of(seen).startswith("QUOTE_NOT_FOUND")
            assert "structuredContent" not in seen and "Lunch" not in json.dumps(seen)

    async def test_cannot_be_approved_even_with_its_id_and_its_own_token(self):
        stack = make_stack()
        alices = await made_by(stack, ALICE)
        stolen = await stack.call_as(BOB, PAY, "approve_quote", **approve_args(alices))
        assert stolen["isError"] is True and text_of(stolen).startswith("QUOTE_NOT_FOUND")
        assert await state_of(stack, quote_of(alices)["id"]) == "open"
        assert await stack.count("quote_events") == 0
        own = await stack.call_as(ALICE, PAY, "approve_quote", **approve_args(alices))
        assert quote_of(own)["phase"] == "awaiting_checkout"

    async def test_cannot_be_declined_even_with_its_id_and_its_own_token(self):
        stack = make_stack()
        alices = await made_by(stack, ALICE)
        refused = await stack.call_as(
            BOB,
            PAY,
            "decline_quote",
            quote_id=quote_of(alices)["id"],
            approval_token=alices["_meta"]["approvalToken"],
        )
        assert text_of(refused).startswith("QUOTE_NOT_FOUND")
        assert await state_of(stack, quote_of(alices)["id"]) == "open"

    async def test_is_not_paid_by_another_owners_verification_of_it(self):
        stack = make_stack()
        alices = await made_by(stack, ALICE)
        approved = await stack.call_as(ALICE, PAY, "approve_quote", **approve_args(alices))
        await stack.complete_checkout(quote_of(approved)["checkoutUrl"], "success")
        settled_by_bob = await stack.call_as(BOB, PAY, "verify_quote", quote_id=quote_of(alices)["id"])
        assert text_of(settled_by_bob).startswith("QUOTE_NOT_FOUND")
        assert await state_of(stack, quote_of(alices)["id"]) == "approved"
        settled = await stack.call_as(ALICE, PAY, "verify_quote", quote_id=quote_of(alices)["id"])
        assert quote_of(settled)["phase"] == "succeeded"

    async def test_looks_exactly_like_a_quote_that_does_not_exist(self):
        stack = make_stack()
        alices = await made_by(stack, ALICE)
        theirs = await stack.call_as(BOB, PAY, "get_quote_status", quote_id=quote_of(alices)["id"])
        nothing = await stack.call_as(BOB, PAY, "get_quote_status", quote_id="qt-00000000000000000000")
        assert text_of(theirs).replace(quote_of(alices)["id"], "X") == text_of(nothing).replace(
            "qt-00000000000000000000", "X"
        )

    async def test_the_same_idempotency_key_makes_a_quote_for_each_owner(self):
        stack = make_stack()
        same = key("shared")
        alices = await made_by(stack, ALICE, idempotency_key=same)
        bobs = await made_by(stack, BOB, idempotency_key=same, amount_kobo=300_000, amount_as_user_said="3k")
        assert quote_of(alices)["id"] != quote_of(bobs)["id"]
        assert quote_of(bobs)["amount"]["kobo"] == 300_000
        assert alices["_meta"]["approvalToken"] != bobs["_meta"]["approvalToken"]


class TestTheDailyLimit:
    async def spend(self, stack, owner, times, amount=3_000_000, said="30k"):
        for _ in range(times):
            made = await made_by(stack, owner, amount_kobo=amount, amount_as_user_said=said)
            approved = await stack.call_as(owner, PAY, "approve_quote", **approve_args(made))
            assert "isError" not in approved

    async def test_is_each_owners_own_in_the_cards_and_in_the_refusal(self):
        stack = make_stack()
        await self.spend(stack, ALICE, 3)
        alices_next = await made_by(stack, ALICE, amount_kobo=1_000_000, amount_as_user_said="10k")
        assert quote_of(alices_next)["limits"]["remainingToday"] == "₦10,000"
        bobs = await made_by(stack, BOB, amount_kobo=3_000_000, amount_as_user_said="30k")
        assert quote_of(bobs)["limits"]["remainingToday"] == "₦100,000"
        over = await made_by(stack, ALICE, amount_kobo=3_000_000, amount_as_user_said="30k")
        assert text_of(over) == (
            "LIMIT_DAILY: ₦30,000 would take today's approved total above the daily limit of ₦100,000 "
            "(₦10,000 left today)."
        )
        approved = await stack.call_as(BOB, PAY, "approve_quote", **approve_args(bobs))
        assert quote_of(approved)["limits"]["remainingToday"] == "₦70,000"

    async def test_holds_across_connectors_for_one_owner_and_not_between_owners(self):
        stack = make_stack()
        await self.spend(stack, ALICE, 3)
        airtime = await stack.call_as(
            ALICE, "airtime", "create_airtime_quote",
            network="mtn", phone="08031234567", amount_kobo=1_500_000,
            amount_as_user_said="15k", idempotency_key=key("air"),
        )  # fmt: skip
        assert text_of(airtime).startswith("LIMIT_DAILY")
        bobs = await stack.call_as(
            BOB, "airtime", "create_airtime_quote",
            network="mtn", phone="08031234567", amount_kobo=1_500_000,
            amount_as_user_said="15k", idempotency_key=key("air"),
        )  # fmt: skip
        assert "isError" not in bobs


class TestTheOwnerHeader:
    async def test_a_quote_belongs_to_the_owner_the_header_names(self):
        stack = make_stack()
        made = await made_by(stack, ALICE)
        row = (await stack.rows("SELECT owner FROM quotes WHERE id = ?", quote_of(made)["id"]))[0]
        assert row["owner"] == ALICE

    @pytest.mark.parametrize("bad", ["", "legacy", ALICE.upper(), ALICE + "00", ALICE[:-1], "z" * 32])
    async def test_a_malformed_owner_is_refused_before_anything_runs(self, bad):
        stack = make_stack()
        for method in ("tools/call", "tools/list", "ping"):
            answer = await stack.mcp(
                PAY,
                method,
                {"name": "create_payment_quote", "arguments": args()},
                headers={OWNER_HEADER: bad},
            )
            assert answer["error"]["message"] == "The owner header is not an owner key."
        assert await stack.count("quotes") == 0

    async def test_nothing_the_caller_sends_in_the_body_names_the_owner(self):
        stack = make_stack()
        body = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "create_payment_quote",
                "arguments": args(),
                "_meta": {"owner": BOB, OWNER_HEADER: BOB, "progressToken": 1},
                "owner": BOB,
            },
        }
        reply = await handle(stack.app, "POST", f"/{PAY}/mcp", {}, json.dumps(body).encode())
        assert "isError" not in json.loads(reply.body)["result"]
        (row,) = await stack.rows("SELECT owner FROM quotes")
        assert row["owner"] == DEFAULT_OWNER

    @pytest.mark.parametrize("field", ["owner", "_meta", "x-ledger-owner", "visitor"])
    async def test_a_tool_takes_no_owner_argument(self, field):
        stack = make_stack()
        refused = await stack.call_as(ALICE, PAY, "create_payment_quote", **args(**{field: BOB}))
        assert refused["isError"] is True and text_of(refused).startswith("Invalid arguments")
        assert await stack.count("quotes") == 0


class TestWhenTheConfigurationRequiresAnOwner:
    async def test_a_tool_call_without_one_is_refused_and_does_nothing(self):
        stack = make_stack(require_owner=True)
        answer = await stack.mcp(PAY, "tools/call", {"name": "create_payment_quote", "arguments": args()})
        assert answer["error"]["message"] == "A tool call must say whose it is."
        assert await stack.count("quotes") == 0

    async def test_a_body_that_names_an_owner_is_no_substitute_for_the_header(self):
        stack = make_stack(require_owner=True)
        answer = await stack.mcp(
            PAY,
            "tools/call",
            {"name": "create_payment_quote", "arguments": args(), "_meta": {"owner": ALICE}, "owner": ALICE},
        )
        assert "error" in answer and await stack.count("quotes") == 0

    async def test_reading_what_the_connector_offers_needs_no_owner(self):
        stack = make_stack(require_owner=True)
        for method, params in (
            ("initialize", {"protocolVersion": "2025-11-25"}),
            ("tools/list", {}),
            ("resources/list", {}),
            ("resources/read", {"uri": "ui://paystack-pay/card.html"}),
            ("ping", {}),
        ):
            assert "result" in await stack.mcp(PAY, method, params)

    async def test_a_tool_call_with_one_runs_for_that_owner(self):
        stack = make_stack(require_owner=True)
        made = await made_by(stack, ALICE)
        assert "isError" not in made
        assert (await stack.call_as(BOB, PAY, "get_quote_status", quote_id=quote_of(made)["id"]))["isError"]

    async def test_a_direct_ledger_use_with_no_owner_is_refused_too(self):
        stack = make_stack(require_owner=True)
        with pytest.raises(Exception, match="whose it is"):
            await stack.payments.create_quote(
                amount_kobo=500_000, amount_as_user_said="5k", description="x", merchant="y",
                merchant_ref=None, idempotency_key=key("direct"),
            )  # fmt: skip


class TestTheHostAloneNamesTheOwner:
    async def test_without_the_bearer_the_header_opens_nothing(self):
        stack = make_stack(mcp_token="t" * 40, require_owner=True)
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode()
        for headers in ({OWNER_HEADER: ALICE}, {OWNER_HEADER: ALICE, "authorization": "Bearer wrong"}):
            reply = await handle(stack.app, "POST", f"/{PAY}/mcp", headers, body)
            assert reply.status == 401
        assert await stack.count("quotes") == 0

    async def test_with_the_bearer_the_header_is_taken_as_named(self):
        stack = make_stack(mcp_token="t" * 40, require_owner=True)
        headers = {"authorization": "Bearer " + "t" * 40, OWNER_HEADER: BOB}
        body = {
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "create_payment_quote", "arguments": args()},
        }  # fmt: skip
        reply = await handle(stack.app, "POST", f"/{PAY}/mcp", headers, json.dumps(body).encode())
        assert "isError" not in json.loads(reply.body)["result"]
        assert [r["owner"] for r in await stack.rows("SELECT owner FROM quotes")] == [BOB]


class TestACardsOrder:
    def order(self):
        return {
            "card_id": "0123456789abcdef0123456789abcdef",
            "items": [{"item_id": "beef-suya", "quantity": 2}],
            "delivery_area": "Surulere",
        }

    async def test_of_the_same_card_id_makes_a_quote_for_each_owner_and_hands_out_no_other_token(self):
        stack = make_stack()
        alices = await stack.call_as(ALICE, "food-order", "order_from_menu", **self.order())
        bobs = await stack.call_as(BOB, "food-order", "order_from_menu", **self.order())
        assert quote_of(alices)["id"] != quote_of(bobs)["id"]
        assert alices["_meta"]["approvalToken"] != bobs["_meta"]["approvalToken"]
        again = await stack.call_as(ALICE, "food-order", "order_from_menu", **self.order())
        assert quote_of(again)["id"] == quote_of(alices)["id"]

    async def test_cannot_be_approved_by_another_owner(self):
        stack = make_stack()
        alices = await stack.call_as(ALICE, "food-order", "order_from_menu", **self.order())
        stolen = await stack.call_as(BOB, "food-order", "approve_quote", **approve_args(alices))
        assert text_of(stolen).startswith("QUOTE_NOT_FOUND")
