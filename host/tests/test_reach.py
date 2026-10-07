# SPDX-License-Identifier: AGPL-3.0-or-later
"""234 as a person's own agent at another Brand (turns/reach/), against a Brand's PACT Provider played by
reach_support.FakeBrand: the personal-agent JWT it signs, the conversation it keeps, the sign-in a step-up
starts and the card that follows it, the delegation it then sends and refreshes, and the receipts it checks
before it keeps them."""

import json

import httpx
import pytest

from signatures.private_key import from_jwk
from turns.hub import ACCOUNT_META, Hub
from turns.reach.config import Reached, ReachSettings
from turns.reach.server import ReachServer

from .reach_support import AUDIENCE, CARD, FakeBrand, agent_key_pair

pytestmark = pytest.mark.django_db
ISSUER = "https://234.example"
ALICE, BOLA = "a" * 32, "b" * 32
SKYLINE = "skyline-airways"


class Clock:
    def __init__(self) -> None:
        self.now = 1_800_000_000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture(scope="module")
def keys():
    return agent_key_pair()


@pytest.fixture
def rig(sql, keys):
    private, public = keys
    brand = FakeBrand(public)
    clock = Clock()
    settings = ReachSettings(ISSUER, from_jwk(private), (Reached(CARD, AUDIENCE),))
    client = httpx.AsyncClient(transport=brand.transport())
    server = ReachServer(settings, sql, client, clock)
    return brand, server, clock


async def call(server, name, owner=ALICE, account=True, **arguments):
    """A call as a signed-in account's, unless `account` is False."""
    params = {"name": name, "arguments": arguments, "_meta": {ACCOUNT_META: account}}
    return await server.request("tools/call", params, owner)


async def ask(server, text, owner=ALICE):
    return (await call(server, "message_brand", owner, brand=SKYLINE, text=text))["structuredContent"]


async def sign_in(brand, server, clock, allowed="flights:upcoming:read"):
    """The person asks for something that needs a scope, allows it at the Brand, and the card sees it."""
    card = await ask(server, "my upcoming flights")
    brand.decide(allowed)
    clock.now += 6
    return (await call(server, "sign_in_status", card_id=card["card_id"]))["structuredContent"]


async def receipts(sql):
    return await sql.rows("SELECT owner, claims FROM reach_receipt")


async def test_the_brands_are_listed_from_their_cards_and_the_model_sees_two_tools(rig):
    _, server, _ = rig
    listed = await call(server, "list_brands")
    assert listed["structuredContent"]["brands"] == [{
        "id": "skyline-airways", "name": "Skyline Airways", "description": "Flight status and trip changes.",
        "skills": ["Flight status"], "allowed": [],
    }]  # fmt: skip
    hub = Hub({}, httpx.AsyncClient(), local={"brands": server})
    assert [t["function"]["name"] for t in await hub.model_tools()] == [
        "brands__list_brands",
        "brands__message_brand",
    ]


async def test_a_message_carries_a_signed_jwt_with_a_sub_per_person_and_brand_and_the_context_continues(rig):
    brand, server, _ = rig
    first = await call(server, "message_brand", brand=SKYLINE, text="Is my Friday flight on time?")
    assert first["structuredContent"]["reply"] == "Seen: Is my Friday flight on time?"
    await call(server, "message_brand", brand=SKYLINE, text="ABC123")
    await call(server, "message_brand", BOLA, brand=SKYLINE, text="hello")
    alice, again, bola = brand.seen
    assert alice["sub"] == again["sub"] != bola["sub"] and len(alice["sub"]) == 32
    assert alice["context"] is None and again["context"] is not None and bola["context"] is None
    assert ALICE not in alice["sub"] and not any(s["delegated"] for s in brand.seen)


async def test_a_step_up_shows_a_sign_in_card_and_the_card_follows_it_at_the_brands_pace(rig):
    brand, server, clock = rig
    asked = await call(server, "message_brand", brand=SKYLINE, text="my upcoming flights")
    card = asked["structuredContent"]
    assert card["sign_in"]["brand"] == "Skyline Airways" and card["sign_in"]["state"] == "pending"
    assert "See your upcoming flights" in asked["content"][0]["text"], "the model is told what the Brand asks"
    assert card["sign_in"]["link"].startswith("https://skyline.example/login") and card["card_id"].startswith(
        "si_"
    )
    status = await call(server, "sign_in_status", card_id=card["card_id"])
    assert status["structuredContent"]["sign_in"]["state"] == "pending"
    brand.decide("flights:upcoming:read")
    clock.now += 2
    early = await call(server, "sign_in_status", card_id=card["card_id"])
    assert early["structuredContent"]["sign_in"]["state"] == "pending", "not before the Brand's interval"
    clock.now += 5
    done = (await call(server, "sign_in_status", card_id=card["card_id"]))["structuredContent"]
    assert done["sign_in"]["state"] == "connected" and done["connected_now"] is True
    again = (await call(server, "sign_in_status", card_id=card["card_id"]))["structuredContent"]
    assert "connected_now" not in again, "only the call that settled it says so"
    assert (await call(server, "sign_in_status", BOLA, card_id=card["card_id"]))["isError"], (
        "nobody else's card"
    )


async def test_after_signing_in_the_request_runs_as_the_person_and_its_receipt_is_checked_and_kept(rig, sql):
    brand, server, clock = rig
    assert (await sign_in(brand, server, clock))["sign_in"]["state"] == "connected"
    answer = await ask(server, "my upcoming flights")
    assert answer["receipt"] == {"scopes_used": ["flights:upcoming:read"], "actions": ["list_upcoming_trips"]}
    assert brand.seen[-1]["delegated"]
    (kept,) = await receipts(sql)
    assert kept["owner"] == ALICE and json.loads(kept["claims"])["pa"] == ISSUER
    listed = (await call(server, "list_brands"))["structuredContent"]["brands"][0]
    assert listed["allowed"] == ["See your upcoming flights"]


async def test_a_receipt_whose_claims_are_not_the_signed_ones_is_not_kept_and_the_person_is_told(rig, sql):
    brand, server, clock = rig
    await sign_in(brand, server, clock)
    brand.tamper_receipt = True
    answer = await call(server, "message_brand", brand=SKYLINE, text="my upcoming flights")
    assert "did not check out" in answer["content"][0]["text"]
    assert "receipt" not in answer["structuredContent"] and await receipts(sql) == []


async def test_a_delegation_near_its_end_is_refreshed_and_one_the_brand_refuses_is_dropped(rig):
    brand, server, clock = rig
    card = (await call(server, "message_brand", brand=SKYLINE, text="my upcoming flights"))[
        "structuredContent"
    ]
    brand.decide("flights:upcoming:read")
    clock.now += 6
    await call(server, "sign_in_status", card_id=card["card_id"])
    first_token = next(iter(brand.tokens))
    clock.now += 3600 - 30
    await call(server, "message_brand", brand=SKYLINE, text="my upcoming flights")
    assert len(brand.tokens) == 2 and brand.seen[-1]["delegated"], "refreshed before it ran out"
    assert first_token in brand.tokens
    brand.reject_tokens = True
    retried = await call(server, "message_brand", brand=SKYLINE, text="my upcoming flights")
    assert "sign_in" in retried["structuredContent"], "a refused token is dropped and the request asks again"


async def test_a_denied_sign_in_ends_as_not_allowed(rig):
    brand, server, clock = rig
    card = (await call(server, "message_brand", brand=SKYLINE, text="please rebook me"))["structuredContent"]
    brand.decide(None)
    clock.now += 6
    shown = (await call(server, "sign_in_status", card_id=card["card_id"]))["structuredContent"]["sign_in"]
    assert shown["state"] == "denied"


async def test_a_conversation_the_brand_no_longer_knows_starts_again(rig):
    brand, server, _ = rig
    await call(server, "message_brand", brand=SKYLINE, text="hello")
    brand.contexts.clear()
    again = await call(server, "message_brand", brand=SKYLINE, text="hello again")
    assert again["structuredContent"]["reply"] == "Seen: hello again" and brand.seen[-1]["context"] is None


async def test_an_unknown_brand_or_an_unreachable_one_is_an_error_the_model_can_read(rig, keys, sql):
    _, server, _ = rig
    assert (await call(server, "message_brand", brand="nope", text="hi"))["isError"]
    private, _ = keys
    settings = ReachSettings(ISSUER, from_jwk(private), (Reached("https://down.example/card.json", "x"),))
    down = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(503)))
    dead = ReachServer(settings, sql, down)
    assert (await call(dead, "list_brands"))["structuredContent"] == {"brands": []}
    assert (await dead.request("resources/list"))["resources"][0]["uri"] == "ui://brands/card.html"


async def test_one_persons_delegation_is_never_sent_for_another(rig):
    brand, server, clock = rig
    await sign_in(brand, server, clock)
    asked = await ask(server, "my upcoming flights", BOLA)
    assert "sign_in" in asked and not brand.seen[-1]["delegated"]


@pytest.mark.parametrize("problem", ["another key", "another agent"])
async def test_a_receipt_signed_by_another_key_or_for_another_agent_is_not_kept(rig, sql, problem):
    from cryptography.hazmat.primitives.asymmetric import ec

    brand, server, clock = rig
    await sign_in(brand, server, clock)
    if problem == "another key":
        brand.receipt_key = ec.generate_private_key(ec.SECP256R1())
    else:
        brand.receipt_pa = "https://another-agent.example"
    answer = await call(server, "message_brand", brand=SKYLINE, text="my upcoming flights")
    assert "did not check out" in answer["content"][0]["text"] and await receipts(sql) == []


async def test_two_cards_polling_at_once_settle_the_sign_in_once(rig):
    """Both read the sign-in while it was pending; the first takes the token, the Brand refuses the second's
    device code, and that refusal must not end a sign-in the first already connected."""
    brand, server, clock = rig
    card = await ask(server, "my upcoming flights")
    brand.decide("flights:upcoming:read")
    clock.now += 6
    seen_by_both = await server._store.sign_in(ALICE, card["card_id"])
    skyline = await server.directory.find(SKYLINE)
    now_ms = int(clock.now * 1000)
    first = await server._signing_in.poll(seen_by_both, skyline, now_ms)
    second = await server._signing_in.poll(seen_by_both, skyline, now_ms)
    assert first == ("connected", True) and second == ("connected", False)


def test_a_persons_sub_differs_at_every_brand_and_for_every_person():
    from turns.reach.agent import sub_for

    assert sub_for(ALICE, CARD) != sub_for(ALICE, "https://other.example/card.json") != sub_for(BOLA, CARD)
    assert sub_for(ALICE, CARD) == sub_for(ALICE, CARD) and ALICE not in sub_for(ALICE, CARD)


async def test_only_a_signed_in_account_is_asked_to_give_its_permission_at_a_brand(rig):
    brand, server, _ = rig
    hub = Hub({}, httpx.AsyncClient(), local={"brands": server})
    arguments = {"brand": SKYLINE, "text": "my upcoming flights"}
    visitor = await hub.call_model_tool("brands__message_brand", arguments, ALICE, "k" * 40)
    assert "only someone signed in to 234 can give it" in visitor.text and not visitor.is_error
    assert "structuredContent" not in visitor.result and brand.devices == {}, "no card, no sign-in started"
    account = await hub.call_model_tool("brands__message_brand", arguments, ALICE, "k" * 40, account=True)
    assert "sign_in" in account.result["structuredContent"] and len(brand.devices) == 1
    hello = await call(server, "message_brand", account=False, brand=SKYLINE, text="hello")
    assert hello["structuredContent"]["reply"] == "Seen: hello", "a visitor still talks to the Brand"


async def test_ending_at_a_brand_revokes_the_grant_there_then_forgets_it(rig, sql):
    brand, server, clock = rig
    await sign_in(brand, server, clock)
    assert await server.end(ALICE, SKYLINE) is True
    assert [hint for hint, _ in brand.revoked] == ["refresh_token", "access_token"]
    assert brand.tokens == {} and brand.refreshes == {}, "the Brand ended the grant"
    assert await sql.rows("SELECT * FROM reach_delegation") == []
    assert await sql.rows("SELECT * FROM reach_conversation") == []
    assert await server.end(ALICE, SKYLINE) is False, "nothing left to end"


@pytest.mark.parametrize("revocation", [None, 503])
async def test_a_brand_that_offers_no_revocation_or_fails_it_is_not_counted_as_ended(rig, sql, revocation):
    brand, server, clock = rig
    await sign_in(brand, server, clock)
    brand.revocation = revocation
    assert await server.end(ALICE, SKYLINE) is False
    assert await sql.rows("SELECT * FROM reach_delegation") == [], "234 forgets its tokens all the same"


async def test_ending_one_persons_brand_leaves_anothers(rig, sql):
    brand, server, clock = rig
    await sign_in(brand, server, clock)
    assert await server.end(BOLA, SKYLINE) is False and brand.revoked == []
    assert len(await sql.rows("SELECT * FROM reach_delegation")) == 1
