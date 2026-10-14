# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Paystack Index a draw's account starts with: signed in at the simulated Index the way a person does it
(the link of the connect card, the Allow button, the redirect's code and state handed to the connector as the chat
host hands them), and Chowdeck linked with a phone number and a code, through the connect card's own tools. No
model is involved, and no test route writes the connection."""

from urllib.parse import parse_qsl, urlencode, urlsplit

import httpx

from .signed_in import SetupFailed, account_call

MERCHANTS = "merchants"
SIGN_IN_WITH = "index:mtn-airtime"
CHOWDECK = "index:chowdeck"
PHONE = "08031234567"
CODE = "123456"
FORM_FIELDS = ("client_id", "redirect_uri", "state", "code_challenge")


async def _allow(http: httpx.AsyncClient, link: str) -> dict[str, str]:
    """Presses Allow on the simulated Index's page: the code and state it sends the browser back with."""
    parts = urlsplit(link)
    origin = f"{parts.scheme}://{parts.netloc}"
    asked = dict(parse_qsl(parts.query))
    page = await http.get(link)
    if page.status_code != 200:
        raise SetupFailed(f"the simulated Index's sign-in page answered {page.status_code}")
    body = urlencode({**{name: asked[name] for name in FORM_FIELDS}, "decision": "allow"})
    sent = await http.post(
        f"{origin}{parts.path}/decision",
        content=body,
        headers={"content-type": "application/x-www-form-urlencoded", "origin": origin},
    )
    if sent.status_code != 302:
        raise SetupFailed(f"the simulated Index did not send the browser back: HTTP {sent.status_code}")
    return dict(parse_qsl(urlsplit(sent.headers["location"]).query))


async def set_up_index(checkout: str, owner: str, index: dict[str, bool]) -> None:
    """The account is connected to the simulated Index, and Chowdeck is linked, as the case says."""
    if not index["connected"]:
        return
    merchant = CHOWDECK if index["chowdeck"] else SIGN_IN_WITH
    async with httpx.AsyncClient(timeout=30) as http:

        async def card_call(tool: str, arguments: dict) -> dict:
            return await account_call(http, checkout, MERCHANTS, owner, tool, arguments)

        opened = (await card_call("connect_account", {"merchant_id": merchant}))["structuredContent"]
        back = await _allow(http, opened["connection"]["link"])
        card = (await card_call("complete_connection", back))["structuredContent"]["card_id"]
        if index["chowdeck"]:
            await card_call("send_link_code", {"card_id": card, "phone": PHONE})
            await card_call("confirm_link_code", {"card_id": card, "phone": PHONE, "code": CODE})
