# SPDX-License-Identifier: AGPL-3.0-or-later
"""A person's Index tokens: sealed at rest and readable by no other owner or key, refreshed a minute before
they run out and when Index answers 401, never lost to two refreshes at once, a failed refresh asking the
person to connect again, and disconnecting forgetting them (and asking Index to revoke them where it
offers that)."""

import asyncio
import json
from urllib.parse import urlencode

from checkout.commerce.index.secretbox import SealError, SecretBox
from checkout.commerce.index.settings import IndexSettings
from checkout.http import handle
from checkout.owner import acting_for, remembering_for
from tests.index_support import (
    AIRTIME,
    account,
    connect,
    ok,
    set_setting,
    text_of,
)
from tests.support import ALICE, BOB, reload_app

KEY = "k" * 40


async def row_of(stack, owner):
    return await stack.db.row("SELECT * FROM index_connection WHERE owner = ?", owner)


def tokens_of(stack):
    return stack.app.contexts["merchants"].index.provider._tokens


async def sim_tokens(stack, kind):
    return [r["token"] for r in await stack.rows("SELECT token FROM sim_index_token WHERE kind = ?", kind)]


class TestSealedAtRest:
    async def test_the_stored_value_is_not_the_token(self, stack):
        await connect(stack)
        held = await row_of(stack, ALICE)
        access = [t for t in await sim_tokens(stack, "access") if t in str(await _all_values(stack))]
        assert held["access_sealed"].startswith("v1.") and held["refresh_sealed"].startswith("v1.")
        assert access == []
        for token in [*await sim_tokens(stack, "access"), *await sim_tokens(stack, "refresh")]:
            assert token not in json.dumps(held)

    async def test_the_registration_secret_is_sealed_too(self, stack):
        await connect(stack)
        client = (await stack.rows("SELECT * FROM index_client"))[0]
        secret = (await stack.rows("SELECT secret FROM sim_index_client"))[0]["secret"]
        assert client["secret_sealed"].startswith("v1.") and secret not in json.dumps(client)

    async def test_another_owners_key_cannot_open_it(self, stack):
        await connect(stack)
        held = await row_of(stack, ALICE)
        box = SecretBox(f"simulated-index-{stack.app.settings.approval_secret}")
        context = "index-connection\n{}\naccess"
        assert box.open(held["access_sealed"], context.format(ALICE)).startswith("at-")
        try:
            box.open(held["access_sealed"], context.format(BOB))
        except SealError:
            return
        raise AssertionError("another owner's context opened it")

    async def test_a_row_copied_to_another_owner_opens_for_nobody(self, stack):
        await connect(stack)
        await stack.db.execute("UPDATE index_connection SET owner = ? WHERE owner = ?", BOB, ALICE)
        assert await tokens_of(stack)._store.connection(BOB) is None
        assert await row_of(stack, BOB) is None

    async def test_a_different_key_cannot_read_it_and_the_person_connects_again(self, stack):
        await connect(stack)
        reload_app(stack, index=IndexSettings(token_key="z" * 40))
        with acting_for(ALICE), remembering_for(ALICE):
            listed = await account(stack, "browse_merchants")
            assert "needs the person to connect" in text_of(listed)
        assert await row_of(stack, ALICE) is None

    async def test_each_person_has_their_own_connection_and_their_own_index_account(self, stack):
        await connect(stack, ALICE)
        await connect(stack, BOB)
        assert {r["owner"] for r in await stack.rows("SELECT owner FROM index_connection")} == {ALICE, BOB}
        await set_account_zap(stack, ALICE)
        mine = await account(stack, "create_quote", ALICE, **_airtime())
        theirs = await account(stack, "create_quote", BOB, **_airtime())
        assert mine["structuredContent"]["quote"]["details"]["balanceAfter"] == "₦49,000"
        assert theirs["structuredContent"]["quote"]["details"]["balanceAfter"] == "₦49,000"
        accounts = {c["account_id"] for c in await _calls(stack) if c["tool"] == "get_balance"}
        assert len(accounts) == 2

    async def test_the_audit_holds_no_token_state_or_code(self, stack):
        await connect(stack)
        spoken = "\n".join(stack.audit_lines)
        for token in [*await sim_tokens(stack, "access"), *await sim_tokens(stack, "refresh")]:
            assert token not in spoken
        assert "code=" not in spoken and "state=" not in spoken and "index.connected" in spoken


class TestRefreshing:
    async def test_a_token_about_to_run_out_is_renewed_before_use(self, stack):
        await connect(stack)
        before = await row_of(stack, ALICE)
        stack.clock.advance(59 * 60 + 30)
        ok(await account(stack, "create_quote", **_airtime()))
        after = await row_of(stack, ALICE)
        assert after["version"] == before["version"] + 1 and after["access_sealed"] != before["access_sealed"]
        assert after["expires_at"] > stack.clock.now()

    async def test_a_token_with_time_left_is_used_as_it_is(self, stack):
        await connect(stack)
        before = await row_of(stack, ALICE)
        stack.clock.advance(10 * 60)
        ok(await account(stack, "create_quote", **_airtime()))
        assert (await row_of(stack, ALICE))["version"] == before["version"]

    async def test_a_401_renews_the_token_and_the_call_goes_through(self, stack):
        await connect(stack)
        before = await row_of(stack, ALICE)
        await handle(stack.app, "POST", "/test/index/expire", {}, b"")
        ok(await account(stack, "create_quote", **_airtime()))
        assert (await row_of(stack, ALICE))["version"] == before["version"] + 1

    async def test_two_refreshes_together_keep_one_result_and_the_connection(self, stack):
        await connect(stack)
        stack.clock.advance(3600)
        with acting_for(ALICE), remembering_for(ALICE):
            both = await asyncio.gather(tokens_of(stack).usable(ALICE), tokens_of(stack).usable(ALICE))
        assert both[0].access == both[1].access
        held = await row_of(stack, ALICE)
        assert held is not None and held["version"] == 2

    async def test_a_refresh_index_refuses_asks_the_person_to_connect_again(self, stack):
        await connect(stack)
        await handle(stack.app, "POST", "/test/index/revoke", {}, b"")
        stack.clock.advance(3600)
        refused = await account(stack, "create_quote", **_airtime())
        assert "connect_account" in text_of(refused) and "isError" in refused
        assert await row_of(stack, ALICE) is None

    async def test_index_not_answering_a_refresh_keeps_the_connection(self, stack):
        await connect(stack)
        stack.clock.advance(3600)
        oauth = stack.app.contexts["merchants"].index.accounts._oauth
        real, oauth._transport = oauth._transport, _Silent()
        refused = await account(stack, "create_quote", **_airtime())
        oauth._transport = real
        assert "INDEX_UNAVAILABLE" in text_of(refused)
        assert await row_of(stack, ALICE) is not None


class TestDisconnecting:
    async def test_forgets_the_tokens_and_the_card_says_so(self, stack):
        card_id = await connect(stack)
        done = ok(await account(stack, "disconnect_account", card_id=card_id))
        shown = done["structuredContent"]["connection"]
        assert shown["state"] == "disconnected" and "remove 234" in shown["notice"]
        assert await row_of(stack, ALICE) is None
        listed = await account(stack, "browse_merchants")
        assert "needs the person to connect" in text_of(listed)

    async def test_asks_index_to_revoke_the_tokens_where_it_offers_that(self, stack):
        await set_setting(stack, "revocation", "1")
        card_id = await connect(stack)
        shown = ok(await account(stack, "disconnect_account", card_id=card_id))["structuredContent"][
            "connection"
        ]
        assert "notice" not in shown
        revoked = await stack.rows("SELECT kind, revoked FROM sim_index_token WHERE account_id IS NOT NULL")
        assert revoked and all(r["revoked"] == 1 for r in revoked)

    async def test_ends_the_persons_other_open_cards_too(self, stack):
        card_id = await connect(stack)
        other = (await account(stack, "connect_account", merchant_id=AIRTIME))["structuredContent"]["card_id"]
        ok(await account(stack, "disconnect_account", card_id=card_id))
        status = ok(await account(stack, "connection_status", card_id=other))["structuredContent"]
        assert status["connection"]["state"] == "disconnected"

    async def test_one_person_disconnecting_leaves_the_other_connected(self, stack):
        card_id = await connect(stack, ALICE)
        await connect(stack, BOB)
        ok(await account(stack, "disconnect_account", ALICE, card_id=card_id))
        assert await row_of(stack, ALICE) is None and await row_of(stack, BOB) is not None

    async def test_a_disconnected_person_can_connect_again(self, stack):
        card_id = await connect(stack)
        ok(await account(stack, "disconnect_account", card_id=card_id))
        await connect(stack)
        assert await row_of(stack, ALICE) is not None


class _Silent:
    async def send(self, *_, **__):
        from checkout.transport import TransportError

        raise TransportError("no answer")


def _airtime():
    from tests.index_support import airtime

    return airtime()


async def _calls(stack):
    from tests.index_support import calls

    return await calls(stack)


async def _all_values(stack):
    return [dict(r) for r in await stack.rows("SELECT * FROM index_connection")]


async def set_account_zap(stack, owner):
    query = urlencode({"zap_kobo": 5_000_000})
    await handle(stack.app, "POST", "/test/index/account", {}, b"", query)
