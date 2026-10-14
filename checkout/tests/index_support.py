# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared by the Paystack Index tests: a person connecting on the card the way they do (opening the link to
the simulated Index, pressing Allow, and the chat host handing the code back), quotes and approvals of Index
merchants, and a reading of what the simulated Index was asked."""

import itertools
import json
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit

from checkout.http import handle
from tests.commerce_support import approval
from tests.support import ALICE, Stack
from tests.wallet_card_support import call

CONNECTOR = "merchants"
AIRTIME = "index:mtn-airtime"
GLO = "index:glo-airtime"
CHOWDECK = "index:chowdeck"
IKEJA = "index:ikeja-electric"
METER = "45012345678"
OTHER_METER = "62109876543"
PHONE = "08031234567"
_keys = itertools.count(1)


def new_key() -> str:
    return f"index-key-{next(_keys):05d}"


async def account(stack: Stack, tool: str, owner: str = ALICE, **arguments: Any) -> dict[str, Any]:
    """A call as a signed-in account; a refusal before the tool ran is the JSON-RPC error itself."""
    answer = await call(stack, CONNECTOR, tool, owner, True, **arguments)
    return answer.get("result", answer)


async def visitor(stack: Stack, tool: str, owner: str = ALICE, **arguments: Any) -> dict[str, Any]:
    answer = await call(stack, CONNECTOR, tool, owner, False, **arguments)
    return answer.get("result", answer)


def text_of(result: dict[str, Any]) -> str:
    return result["content"][0]["text"]


def ok(result: dict[str, Any]) -> dict[str, Any]:
    assert not result.get("isError"), text_of(result)
    return result


async def index_page(stack: Stack, link: str, decision: str = "allow") -> str:
    """What the person does at Index: opens the link, presses a button. The address Index sends the browser
    to next, with its code and state."""
    parts = urlsplit(link)
    path, query = parts.path, parts.query
    page = await handle(stack.app, "GET", path, {}, b"", query)
    assert page.status == 200, page.body
    form = dict(parse_qsl(query))
    body = urlencode(
        {
            **{k: form[k] for k in ("client_id", "redirect_uri", "state", "code_challenge")},
            "decision": decision,
        }
    )
    origin = stack.app.settings.public_base_url.rstrip("/")
    sent = await handle(stack.app, "POST", f"{path}/decision", {"origin": origin}, body.encode())
    assert sent.status == 302, sent.body
    return sent.headers["location"]


def callback_of(location: str) -> dict[str, str]:
    return dict(parse_qsl(urlsplit(location).query))


async def start_connecting(stack: Stack, owner: str = ALICE, merchant: str = AIRTIME) -> dict[str, Any]:
    made = ok(await account(stack, "connect_account", owner, merchant_id=merchant))
    return made["structuredContent"]


async def connect(stack: Stack, owner: str = ALICE, merchant: str = AIRTIME) -> str:
    """The person connects their Index account on the card; the id of the card."""
    card = await start_connecting(stack, owner, merchant)
    returned = callback_of(await index_page(stack, card["connection"]["link"]))
    done = ok(
        await account(stack, "complete_connection", owner, code=returned["code"], state=returned["state"])
    )
    assert done["structuredContent"]["card_id"] == card["card_id"]
    return card["card_id"]


async def link_chowdeck(stack: Stack, card_id: str, owner: str = ALICE, phone: str = PHONE) -> dict[str, Any]:
    ok(await account(stack, "send_link_code", owner, card_id=card_id, phone=phone))
    done = ok(await account(stack, "confirm_link_code", owner, card_id=card_id, phone=phone, code="123456"))
    return done["structuredContent"]


async def set_account(stack: Stack, **columns: Any) -> None:
    query = urlencode(columns)
    changed = await handle(stack.app, "POST", "/test/index/account", {}, b"", query)
    assert changed.status == 200, changed.body


async def set_setting(stack: Stack, name: str, value: str) -> None:
    changed = await handle(
        stack.app, "POST", "/test/index/setting", {}, b"", urlencode({"name": name, "value": value})
    )
    assert changed.status == 200, changed.body


async def calls(stack: Stack) -> list[dict[str, Any]]:
    return json.loads((await handle(stack.app, "GET", "/test/index/calls", {}, b"")).body)["calls"]


async def tools_called(stack: Stack, *, confirmed: bool | None = None) -> list[str]:
    return [c["tool"] for c in await calls(stack) if confirmed is None or c["confirmed"] is confirmed]


def airtime(merchant: str = AIRTIME, amount: int = 100_000, **over: Any) -> dict[str, Any]:
    """A quote request for ₦1,000 of airtime."""
    naira = amount // 100
    return {
        "merchant_id": merchant,
        "lines": [{"offer_id": "airtime"}],
        "amount_kobo": amount,
        "amount_as_user_said": f"{naira} naira",
        "fields": {"phone": PHONE},
        "idempotency_key": new_key(),
        **over,
    }


async def electricity_check(
    stack: Stack, owner: str = ALICE, meter: str = METER, merchant: str = IKEJA
) -> dict:
    fields = {"meter_type": "prepaid", "meter_number": meter}
    return await account(stack, "check_account", owner, merchant_id=merchant, fields=fields)


def electricity(check_id: str, amount: int = 200_000, **over: Any) -> dict[str, Any]:
    return {
        "merchant_id": IKEJA,
        "lines": [{"offer_id": "electricity"}],
        "amount_kobo": amount,
        "amount_as_user_said": f"{amount // 100} naira",
        "fields": {"meter_type": "prepaid", "meter_number": METER},
        "check_id": check_id,
        "idempotency_key": new_key(),
        **over,
    }


async def quote(stack: Stack, owner: str = ALICE, **request: Any) -> dict[str, Any]:
    return ok(await account(stack, "create_quote", owner, **(request or airtime())))


async def press_approve(
    stack: Stack, made: dict[str, Any], owner: str = ALICE, **over: Any
) -> dict[str, Any]:
    arguments = {**approval(made), "funding": "external", **over}
    return await account(stack, "approve_quote", owner, **arguments)


async def zap_of(stack: Stack) -> int:
    row = await stack.db.row(
        "SELECT zap_kobo FROM sim_index_account ORDER BY created_at DESC, rowid DESC LIMIT 1"
    )
    return row["zap_kobo"]
