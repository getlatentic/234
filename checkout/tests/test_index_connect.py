# SPDX-License-Identifier: AGPL-3.0-or-later
"""A person connecting their own Paystack Index account from a card: the sign-in with PKCE and a state that
is taken once and only for the person's own attempt, the one client 234 registers for a deployment, a
wrong state, a replayed code, a late sign-in, a refusal, and a visitor who cannot connect at all."""

from urllib.parse import parse_qsl, urlsplit

from tests.index_support import (
    AIRTIME,
    account,
    callback_of,
    connect,
    index_page,
    ok,
    start_connecting,
    text_of,
    visitor,
)
from tests.support import ALICE, BOB


async def complete(stack, owner, returned):
    return await account(stack, "complete_connection", owner, code=returned["code"], state=returned["state"])


async def status(stack, card_id, owner=ALICE):
    return ok(await account(stack, "connection_status", owner, card_id=card_id))["structuredContent"][
        "connection"
    ]


async def rows(stack, table):
    return await stack.rows(f"SELECT * FROM {table}")


class TestTheCard:
    async def test_asks_the_person_to_sign_in_at_index_with_pkce_and_a_state(self, stack):
        card = await start_connecting(stack)
        link = urlsplit(card["connection"]["link"])
        asked = dict(parse_qsl(link.query))
        assert link.path == "/sim/index/authorize"
        assert asked["response_type"] == "code" and asked["scope"] == "mcp:transact"
        assert asked["code_challenge_method"] == "S256" and len(asked["code_challenge"]) == 43
        assert asked["redirect_uri"] == "http://localhost:8787/connect/index/callback"
        assert len(asked["state"]) >= 40 and card["connection"]["state"] == "authorize"
        assert card["card_id"].startswith("cn-")

    async def test_the_model_is_told_what_it_may_not_do_and_nothing_secret(self, stack):
        made = ok(await account(stack, "connect_account", merchant_id=AIRTIME))
        told = text_of(made)
        assert "never see" in told and "must not ask for a code" in told
        link = made["structuredContent"]["connection"]["link"]
        assert link not in told and "state=" not in told and "_meta" not in made

    async def test_connected_after_the_person_signs_in_and_the_host_hands_the_code_back(self, stack):
        card_id = await connect(stack)
        assert (await status(stack, card_id))["state"] == "connected"

    async def test_a_second_card_for_a_connected_person_is_already_connected(self, stack):
        await connect(stack)
        again = await start_connecting(stack)
        assert again["connection"]["state"] == "connected" and "link" not in again["connection"]

    async def test_a_card_for_the_account_itself_names_no_merchant(self, stack):
        made = ok(await account(stack, "connect_account"))
        shown = made["structuredContent"]["connection"]
        assert shown["merchant"] is None and shown["state"] == "authorize" and "link" in shown
        returned = callback_of(await index_page(stack, shown["link"]))
        done = ok(await complete(stack, ALICE, returned))
        assert done["structuredContent"]["connection"] == {
            "provider": "Paystack Index",
            "merchant": None,
            "state": "connected",
            "interval": 3,
        }

    async def test_names_nothing_but_index_merchants_to_connect_for(self, stack):
        refused = await account(stack, "connect_account", merchant_id="mama-put-yaba")
        assert "needs no account" in text_of(refused)

    async def test_registers_one_client_for_the_deployment_however_many_people_connect(self, stack):
        await connect(stack, ALICE)
        await connect(stack, BOB)
        assert len(await rows(stack, "index_client")) == 1
        assert len(await rows(stack, "sim_index_client")) == 1


class TestTheStateAndTheCode:
    async def test_a_wrong_state_connects_nothing_and_leaves_the_real_one_good(self, stack):
        card = await start_connecting(stack)
        returned = callback_of(await index_page(stack, card["connection"]["link"]))
        refused = await complete(stack, ALICE, {**returned, "state": "forged-state"})
        assert "INDEX_STATE" in text_of(refused)
        assert await rows(stack, "index_connection") == []
        assert "isError" not in await complete(stack, ALICE, returned)

    async def test_a_state_is_taken_once_so_a_replayed_callback_connects_nothing_more(self, stack):
        card = await start_connecting(stack)
        returned = callback_of(await index_page(stack, card["connection"]["link"]))
        ok(await complete(stack, ALICE, returned))
        before = await rows(stack, "index_connection")
        assert "INDEX_STATE" in text_of(await complete(stack, ALICE, returned))
        assert await rows(stack, "index_connection") == before

    async def test_a_replayed_code_under_a_fresh_state_is_refused_by_index(self, stack):
        first = await start_connecting(stack)
        used = callback_of(await index_page(stack, first["connection"]["link"]))
        ok(await complete(stack, ALICE, used))
        await account(stack, "disconnect_account", card_id=first["card_id"])
        second = await start_connecting(stack)
        fresh = callback_of(await index_page(stack, second["connection"]["link"]))
        refused = await complete(stack, ALICE, {"code": used["code"], "state": fresh["state"]})
        assert "INDEX_SIGN_IN_FAILED" in text_of(refused)
        assert await rows(stack, "index_connection") == []
        assert (await status(stack, second["card_id"]))["state"] == "expired"

    async def test_the_state_of_one_person_is_no_good_to_another(self, stack):
        card = await start_connecting(stack, ALICE)
        returned = callback_of(await index_page(stack, card["connection"]["link"]))
        assert "INDEX_STATE" in text_of(await complete(stack, BOB, returned))
        assert await rows(stack, "index_connection") == []
        ok(await complete(stack, ALICE, returned))
        assert [r["owner"] for r in await rows(stack, "index_connection")] == [ALICE]

    async def test_a_sign_in_that_took_too_long_connects_nothing(self, stack):
        card = await start_connecting(stack)
        returned = callback_of(await index_page(stack, card["connection"]["link"]))
        stack.clock.advance(11 * 60)
        assert "INDEX_STATE" in text_of(await complete(stack, ALICE, returned))
        assert (await status(stack, card["card_id"]))["state"] == "expired"

    async def test_the_state_is_kept_only_as_a_hash_and_the_verifier_sealed_until_the_sign_in_ends(
        self, stack
    ):
        card = await start_connecting(stack)
        state = dict(parse_qsl(urlsplit(card["connection"]["link"]).query))["state"]
        held = (await rows(stack, "index_attempt"))[0]
        assert state not in str(held) and held["state_hash"] and held["verifier_sealed"].startswith("v1.")
        ok(await complete(stack, ALICE, callback_of(await index_page(stack, card["connection"]["link"]))))
        done = (await rows(stack, "index_attempt"))[0]
        assert done["state_hash"] is None and done["verifier_sealed"] is None

    async def test_a_refused_sign_in_ends_the_attempt_and_the_card_can_try_again(self, stack):
        card = await start_connecting(stack)
        returned = callback_of(await index_page(stack, card["connection"]["link"], decision="deny"))
        assert returned["error"] == "access_denied" and "code" not in returned
        ok(await account(stack, "connection_declined", state=returned["state"]))
        assert (await status(stack, card["card_id"]))["state"] == "denied"
        again = ok(await account(stack, "restart_connection", card_id=card["card_id"]))
        assert again["structuredContent"]["connection"]["state"] == "authorize"
        assert "link" in again["structuredContent"]["connection"]

    async def test_a_restarted_card_makes_the_old_link_useless(self, stack):
        card = await start_connecting(stack)
        old = callback_of(await index_page(stack, card["connection"]["link"]))
        ok(await account(stack, "restart_connection", card_id=card["card_id"]))
        assert "INDEX_STATE" in text_of(await complete(stack, ALICE, old))

    async def test_index_not_answering_ends_the_sign_in_without_a_connection(self, stack):
        card = await start_connecting(stack)
        returned = callback_of(await index_page(stack, card["connection"]["link"]))
        parts = stack.app.contexts["merchants"].index
        parts.accounts._oauth._transport = _Down()
        refused = await complete(stack, ALICE, returned)
        assert "INDEX_SIGN_IN_FAILED" in text_of(refused) and await rows(stack, "index_connection") == []


class _Down:
    async def send(self, *_, **__):
        from checkout.transport import TransportError

        raise TransportError("down")


class TestOnlyAnAccountConnects:
    async def test_a_visitor_cannot_open_the_card(self, stack):
        refused = await visitor(stack, "connect_account", merchant_id=AIRTIME)
        assert "ACCOUNT_ONLY" in text_of(refused)
        assert await rows(stack, "index_attempt") == []

    async def test_a_visitor_cannot_hand_a_code_back_or_use_a_card(self, stack):
        card = await start_connecting(stack)
        returned = callback_of(await index_page(stack, card["connection"]["link"]))
        assert "ACCOUNT_ONLY" in text_of(await visitor(stack, "complete_connection", **returned))
        assert "ACCOUNT_ONLY" in text_of(await visitor(stack, "disconnect_account", card_id=card["card_id"]))
        assert await rows(stack, "index_connection") == []

    async def test_a_visitor_sees_no_index_merchant(self, stack):
        await connect(stack)
        listed = await visitor(stack, "browse_merchants")
        assert "index:" not in text_of(listed)

    async def test_nobody_reads_or_ends_another_persons_card(self, stack):
        card = await start_connecting(stack, ALICE)
        assert "CARD_NOT_FOUND" in text_of(
            await account(stack, "connection_status", BOB, card_id=card["card_id"])
        )
        assert "CARD_NOT_FOUND" in text_of(
            await account(stack, "disconnect_account", BOB, card_id=card["card_id"])
        )
        assert "CARD_NOT_FOUND" in text_of(
            await account(stack, "restart_connection", BOB, card_id=card["card_id"])
        )
