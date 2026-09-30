# SPDX-License-Identifier: AGPL-3.0-or-later
"""The simulated Paystack checkout page: what it shows, what it lets in, and the chat link it offers."""

import base64
import hashlib
import re

import pytest

from checkout.http import handle
from tests.support import make_stack

CHAT = "/c/" + "a1" * 16
HOST = "https://chat.example"
ORIGIN = "http://localhost:8787"


async def issue(stack, **over):
    """An approved payment quote and its checkout reference."""
    flow = stack.payments
    args = {
        "amount_kobo": 250_000,
        "amount_as_user_said": "2500",
        "description": "Lunch",
        "merchant": "Demo Kitchen",
        "merchant_ref": None,
        "idempotency_key": "page-key-000001",
        **over,
    }
    issued = await flow.create_quote(**args)
    approved = await flow.approve(issued.quote["id"], issued.approval_token, args["amount_kobo"])
    return issued.quote["id"], approved["checkoutUrl"].rsplit("/", 1)[1]


async def get(stack, reference, query=""):
    return await handle(stack.app, "GET", f"/sim/checkout/{reference}", {}, b"", query)


async def press(stack, reference, button, query="", headers=None):
    path = f"/sim/checkout/{reference}/{button}"
    return await handle(stack.app, "POST", path, headers or {}, b"", query)


def texts(html: str) -> list[str]:
    body = re.sub(r"<(style|script)>.*?</\1>", "", html, flags=re.S)
    return [t.strip() for t in re.split(r"<[^>]+>", body) if t.strip()]


class TestTheOpenPage:
    async def test_is_one_column_with_who_amount_and_three_actions_and_nothing_explained(self):
        stack = make_stack()
        _, reference = await issue(stack)
        page = await get(stack, reference)
        assert page.status == 200
        assert texts(page.body) == [
            "Simulated Paystack checkout",
            "Simulated: no money moves",
            "Demo Kitchen · Lunch",
            "₦2,500",
            "Pay with a test card",
            "Use a declined card",
            "Close without paying",
        ]

    async def test_does_not_repeat_the_merchant_when_the_description_names_it(self):
        stack = make_stack()
        flow = stack.airtime
        issued = await flow.create_airtime_quote(
            network="mtn", phone="08031234567", amount_kobo=50_000, amount_as_user_said="₦500",
            idempotency_key="page-airtime-0001",
        )  # fmt: skip
        approved = await flow.approve(issued.quote["id"], issued.approval_token, 50_000, True)
        page = await get(stack, approved["checkoutUrl"].rsplit("/", 1)[1])
        assert texts(page.body)[2:4] == ["MTN airtime", "₦500"]

    async def test_escapes_the_merchant_and_the_description(self):
        stack = make_stack()
        _, reference = await issue(
            stack, merchant="<b>Evil</b>", description='"><img src=x onerror=alert(1)>'
        )
        body = (await get(stack, reference)).body
        assert "<b>Evil" not in body and "<img" not in body

    async def test_is_served_with_a_policy_that_lets_in_only_its_own_style_and_script(self):
        stack = make_stack()
        _, reference = await issue(stack)
        page = await press(stack, reference, "pay")
        policy = page.headers["content-security-policy"]
        style = re.search(r"<style>(.*?)</style>", page.body, re.S).group(1)
        script = re.search(r"<script>(.*?)</script>", page.body, re.S).group(1)
        for source in (style, script):
            digest = "sha256-" + base64.b64encode(hashlib.sha256(source.encode()).digest()).decode()
            assert f"'{digest}'" in policy
        assert "default-src 'none'" in policy and "form-action 'self'" in policy
        assert "frame-ancestors 'none'" in policy and "unsafe-inline" not in policy
        assert page.headers["cache-control"] == "no-store"
        assert page.headers["referrer-policy"] == "same-origin"
        assert len(re.findall(r"<script", page.body)) == 1 and " on" not in re.sub(r'"[^"]*"', "", page.body)

    async def test_declares_light_and_dark_and_the_phone_screen(self):
        stack = make_stack()
        _, reference = await issue(stack)
        body = (await get(stack, reference)).body
        needles = ("prefers-color-scheme: dark", "100dvh", "safe-area-inset-bottom", "min-height:2.75rem")
        for needle in needles:
            assert needle in body
        assert "viewport-fit=cover" in body and "focus-visible" in body and "tabular-nums" in body


class TestAfterAPress:
    @pytest.mark.parametrize(
        ("button", "word"), [("pay", "Paid"), ("decline", "Declined"), ("close", "Closed")]
    )
    async def test_shows_one_state_line_and_no_buttons(self, button, word):
        stack = make_stack()
        _, reference = await issue(stack)
        page = await press(stack, reference, button)
        assert texts(page.body)[-1] == word
        assert page.body.count('role="status"') == 1 and "<button" not in page.body
        assert "window.close()" in page.body

    async def test_reading_a_finished_checkout_again_shows_its_state_and_still_no_buttons(self):
        stack = make_stack()
        _, reference = await issue(stack)
        await press(stack, reference, "pay")
        again = await get(stack, reference)
        assert texts(again.body)[-1] == "Paid" and "<button" not in again.body

    async def test_the_open_page_does_not_try_to_close_itself(self):
        stack = make_stack()
        _, reference = await issue(stack)
        assert "window.close" not in (await get(stack, reference)).body

    async def test_returns_to_the_chat_when_the_chat_is_known(self):
        stack = make_stack(host_public_url=HOST)
        _, reference = await issue(stack)
        opened = await get(stack, reference, f"back={CHAT}")
        assert f"/pay?back={CHAT}" in opened.body
        page = await press(stack, reference, "pay", f"back={CHAT}")
        assert f'<a class="back" href="{HOST}{CHAT}">Return to the chat</a>' in page.body

    async def test_takes_the_chat_address_with_its_trailing_slash_as_the_host_writes_it(self):
        stack = make_stack(host_public_url=HOST)
        _, reference = await issue(stack)
        page = await press(stack, reference, "pay", f"back={CHAT}/")
        assert f'href="{HOST}{CHAT}/"' in page.body

    @pytest.mark.parametrize(
        "back",
        ["//evil.example/c/" + "a1" * 16, "https://evil.example", "/c/short", "/other", CHAT + "/x", ""],
    )
    async def test_offers_no_link_for_a_chat_it_cannot_vouch_for(self, back):
        stack = make_stack(host_public_url=HOST)
        _, reference = await issue(stack)
        page = await press(stack, reference, "pay", f"back={back}")
        assert "Return to the chat" not in page.body and "evil" not in page.body

    async def test_offers_no_link_when_the_host_is_not_known(self):
        stack = make_stack()
        _, reference = await issue(stack)
        page = await press(stack, reference, "pay", f"back={CHAT}")
        assert "Return to the chat" not in page.body

    async def test_still_refuses_a_press_posted_from_another_origin(self):
        stack = make_stack()
        _, reference = await issue(stack)
        refused = await press(stack, reference, "pay", headers={"origin": "https://evil.example"})
        assert refused.status == 403
        assert "Pay with a test card" in (await get(stack, reference)).body
        accepted = await press(stack, reference, "pay", headers={"origin": ORIGIN})
        assert accepted.status == 200 and texts(accepted.body)[-1] == "Paid"
