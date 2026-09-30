# SPDX-License-Identifier: AGPL-3.0-or-later
"""The menu card against the running Workers (local workerd and D1): the host's own hub reading the real
food connector, and a person's chat asking for the menu and ordering through the card relay. Run with the
stack up (`pytest -m worker`); CHECKOUT_URL names the connector Worker."""

import json
import os

import httpx
import pytest

from turns.hub import HubError, build_hub

from .worker_client import FAKE_MODEL, HOST, Visitor, finished, until

pytestmark = pytest.mark.worker
CHECKOUT = os.environ.get("CHECKOUT_URL", "http://localhost:8900")
MENU = "ui://food-order/menu.html"
APPROVAL = "ui://food-order/card.html"
OWNER = "ab" * 16
KEY = "k" * 40
ITEMS = [{"item_id": "zobo", "quantity": 2}, {"item_id": "beef-suya", "quantity": 1}]
ITEM_WORDS = ("Zobo", "Beef suya", "Jollof", "Chapman", "₦")


@pytest.fixture
async def hub():
    async with httpx.AsyncClient(timeout=30) as client:
        yield build_hub(CHECKOUT, ("food-order",), client)


async def test_the_model_is_offered_the_search_and_never_the_order_tool(hub):
    names = {t["function"]["name"] for t in await hub.model_tools()}
    assert "food-order__search_menu" in names and "food-order__order_from_menu" not in names


async def test_the_model_is_refused_the_order_tool_by_the_hub(hub):
    outcome = await hub.call_model_tool(
        "food-order__order_from_menu",
        {"card_id": "a" * 32, "items": ITEMS, "delivery_area": "Yaba"},
        OWNER,
        KEY,
    )
    assert outcome.is_error and "not available to the model" in outcome.text


async def test_a_card_is_refused_the_model_only_tool(hub):
    with pytest.raises(HubError, match="not available to cards"):
        await hub.call_app_tool("food-order", "search_menu", {}, OWNER)


async def test_the_search_gives_the_model_a_line_and_the_card_the_menu(hub):
    outcome = await hub.call_model_tool("food-order__search_menu", {}, OWNER, KEY)
    assert outcome.card_uri == MENU and "\n" not in outcome.text
    assert not any(word in outcome.text for word in ITEM_WORDS)
    assert len(outcome.result["structuredContent"]["items"]) == 11


async def test_the_order_tool_answers_a_card_and_opens_the_approval_card(hub):
    menu = await hub.call_model_tool("food-order__search_menu", {}, OWNER, KEY)
    order = {"card_id": menu.result["structuredContent"]["card_id"], "items": ITEMS, "delivery_area": "Yaba"}
    made = await hub.call_app_tool("food-order", "order_from_menu", order, OWNER)
    assert made["_meta"]["ui"] == {"resourceUri": APPROVAL} and len(made["_meta"]["approvalToken"]) == 64
    assert made["structuredContent"]["quote"]["amount"]["kobo"] == 2 * 80_000 + 350_000 + 120_000


async def test_the_menu_view_is_read_with_no_image_origin(hub):
    page = await hub.read_card("food-order", MENU)
    assert "order_from_menu" in page.html and "csp" not in page.ui


async def ask_for_the_menu(v: Visitor) -> tuple[str, dict, list[dict]]:
    chat = await v.new_chat()
    await v.send(chat, "What is on the menu?")
    events = await until(v.sse(chat), finished)
    return chat, next(e for e in events if e["type"] == "card"), events


async def relay(v: Visitor, chat: str, name: str, arguments: dict) -> httpx.Response:
    return await v.post(f"/c/{chat}/call", {"server": "food-order", "name": name, "arguments": arguments})


async def test_a_chat_asks_for_the_menu_and_orders_through_the_relay_from_two_tabs():
    async with Visitor() as v:
        chat, menu, events = await ask_for_the_menu(v)
        assert events[-1]["payload"]["reason"] == "completed"
        assert (
            menu["payload"]["resource_uri"] == MENU
            and menu["ref"] == menu["payload"]["result"]["structuredContent"]["card_id"]
        )
        assert not any(
            word in "".join(e["payload"].get("text", "") for e in events if e["type"] == "assistant")
            for word in ITEM_WORDS
        )
        order = {"card_id": menu["ref"], "items": ITEMS, "delivery_area": "Ikeja GRA"}

        other = v.another_tab()
        async with other:
            first = await relay(v, chat, "order_from_menu", order)
            second = await relay(other, chat, "order_from_menu", order)
        assert first.status_code == second.status_code == 200 and first.json() == second.json()
        told = first.json()
        assert set(told) == {"content", "structuredContent"} and "approvalToken" not in json.dumps(told)
        quote_id = told["structuredContent"]["spawned"]["ref"]

        log = await v.log(chat)
        kinds = [e["type"] for e in log]
        assert (
            kinds.count("card") == 2 and kinds.count("card_state") == 1 and kinds.count("card_context") == 1
        )
        opened = next(e for e in log if e["type"] == "card" and e["ref"] == quote_id)
        assert opened["payload"]["resource_uri"] == APPROVAL and opened["task"] is None
        assert len(opened["payload"]["result"]["_meta"]["approvalToken"]) == 64
        assert next(e for e in log if e["type"] == "card_state")["ref"] == menu["ref"]
        assert log == await other.another_tab().log(chat)


async def test_a_card_cannot_reach_a_tool_of_another_view_or_a_card_of_another_chat():
    async with Visitor() as v:
        chat, menu, _ = await ask_for_the_menu(v)
        assert (await relay(v, chat, "search_menu", {"card_id": menu["ref"]})).status_code == 403
        assert (await relay(v, chat, "approve_quote", {"card_id": menu["ref"]})).status_code == 403
        stranger = {"card_id": "b" * 32, "items": ITEMS, "delivery_area": "Yaba"}
        assert (await relay(v, chat, "order_from_menu", stranger)).status_code == 403
        async with Visitor() as elsewhere:
            other = await elsewhere.new_chat()
            await elsewhere.send(other, "hello")
            order = {"card_id": menu["ref"], "items": ITEMS, "delivery_area": "Yaba"}
            assert (await relay(elsewhere, other, "order_from_menu", order)).status_code == 403


async def test_the_model_is_never_sent_the_approval_token_after_an_order():
    async with httpx.AsyncClient() as fake:
        await fake.get(f"{FAKE_MODEL}/v1/_reset")
        async with Visitor() as v:
            chat, menu, _ = await ask_for_the_menu(v)
            told = await relay(
                v, chat, "order_from_menu", {"card_id": menu["ref"], "items": ITEMS, "delivery_area": "Yaba"}
            )
            assert told.status_code == 200
            await v.send(chat, "thanks")
            await until(v.sse(chat, since=0), lambda e: e["type"] == "turn.finished" and e["seq"] > 12)
            sent = json.dumps(
                [
                    r["messages"]
                    for r in (await fake.get(f"{FAKE_MODEL}/v1/_requests")).json()
                    if r.get("tools")
                ]
            )
            assert "approvalToken" not in sent and "[card update] The person's menu made quote qt-" in sent
            assert not any(word in sent for word in ITEM_WORDS)


async def test_the_menu_card_is_served_to_the_chat_as_json_with_no_origin_to_load_from():
    async with Visitor() as v:
        chat, _, _ = await ask_for_the_menu(v)
        page = await v.http.get(f"{HOST}/c/{chat}/card", params={"server": "food-order", "uri": MENU})
        card = page.json()
        assert page.status_code == 200 and "order_from_menu" in card["html"]
        assert card["csp"] == {} and card["hosts"] == [] and card["permissions"] == {}
