# SPDX-License-Identifier: AGPL-3.0-or-later
"""Telling the chat host that a payment moved: the signed call, its limits, and that nothing it does can
break the payment."""

import asyncio
import hashlib
import hmac
import json

import pytest

from checkout.audit import Audit
from checkout.config import PaymentWebhookSettings, Settings
from checkout.errors import ConfigError
from checkout.http import handle
from checkout.transport import Reply, TransportError
from checkout.webhook import NoNotifier, SignedWebhook
from tests.support import FakeClock, ScriptedTransport, make_stack

URL = "https://chat.internal/hooks/payment"
SECRET = "dummy-hook-secret"
QUOTE = "qt-" + "0123456789abcdef0123"
SHARED_VECTOR = "sha256=4ddeb5f2beb31507dd8b828da070ff29ff98d032a72790db3938d5b4bb684946"


def hook(transport, timeout=1.0):
    lines: list[str] = []
    clock = FakeClock()
    settings = PaymentWebhookSettings(URL, SECRET)
    return SignedWebhook(settings, transport, Audit([lines.append], clock), timeout), lines


def ok(_):
    return Reply(200, '{"pushed": true}', "application/json")


class RecordingNotifier:
    def __init__(self) -> None:
        self.moved: list[str] = []

    async def payment_moved(self, quote_id: str) -> None:
        self.moved.append(quote_id)


class TestTheSignedCall:
    async def test_posts_the_quote_id_to_the_configured_address_signed_with_the_secret(self):
        transport = ScriptedTransport(ok)
        webhook, lines = hook(transport)
        await webhook.payment_moved(QUOTE)
        (sent,) = transport.calls
        body = json.dumps({"quote_id": QUOTE}, separators=(",", ":"))
        assert (sent.method, sent.url) == ("POST", URL)
        assert (
            sent.headers["x-signature"]
            == "sha256=" + hmac.new(SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()
        )
        assert sent.body == {"quote_id": QUOTE} and sent.headers["content-type"] == "application/json"
        assert json.loads(lines[0])["event"] == "webhook.sent"

    async def test_signs_the_way_the_host_verifies(self):
        """The same vector is asserted by the host's own test (host/tests/test_hooks.py)."""
        transport = ScriptedTransport(ok)
        webhook, _ = hook(transport)
        await webhook.payment_moved("qt-1")
        assert transport.calls[0].headers["x-signature"] == SHARED_VECTOR

    @pytest.mark.parametrize(
        "failure",
        [
            TransportError("fetch failed"),
            RuntimeError("the binding is gone"),
            Reply(401, "", None),
            Reply(500, "boom", None),
            Reply(302, "", None),
        ],
        ids=["no connection", "a bug", "refused", "host error", "redirect"],
    )
    async def test_a_failing_host_is_logged_in_one_line_and_never_raised(self, failure):
        webhook, lines = hook(ScriptedTransport(lambda _: failure))
        await webhook.payment_moved(QUOTE)
        assert len(lines) == 1 and json.loads(lines[0])["event"] in ("webhook.failed", "webhook.refused")
        assert SECRET not in lines[0] and "the binding is gone" not in lines[0]

    async def test_a_host_that_does_not_answer_is_given_up_on(self):
        class Silent:
            async def send(self, *_, **__):
                await asyncio.sleep(30)

        webhook, lines = hook(Silent(), timeout=0.05)
        await asyncio.wait_for(webhook.payment_moved(QUOTE), 2)
        assert json.loads(lines[0])["why"] == "TimeoutError"

    async def test_nothing_is_called_when_no_webhook_is_configured(self):
        await NoNotifier().payment_moved(QUOTE)


class TestSettings:
    def read(self, **env):
        return Settings.from_env({"APPROVAL_SECRET": "x-not-real", **env}.get)

    def test_is_on_with_an_address_and_a_secret(self):
        found = self.read(PAYMENT_WEBHOOK_URL=URL, WEBHOOK_SECRET=SECRET, PAYMENT_WEBHOOK_BINDING="HOST")
        assert found.payment_webhook == PaymentWebhookSettings(URL, SECRET, "HOST")

    @pytest.mark.parametrize("env", [{}, {"PAYMENT_WEBHOOK_URL": URL}, {"WEBHOOK_SECRET": SECRET}])
    def test_is_off_without_both(self, env):
        assert self.read(**env).payment_webhook is None

    def test_a_local_host_may_be_reached_over_plain_http(self):
        local = "http://localhost:8901/hooks/payment"
        assert self.read(PAYMENT_WEBHOOK_URL=local, WEBHOOK_SECRET=SECRET).payment_webhook.url == local

    @pytest.mark.parametrize(
        "url",
        [
            "http://chat.example/hooks/payment",
            "https://chat.example/hooks/other",
            "https://chat.example/",
            "https://chat.example/hooks/payment?next=https://evil.example",
            "https://user:pass@chat.example/hooks/payment",
            "ftp://chat.example/hooks/payment",
        ],
    )
    def test_refuses_an_address_that_is_not_the_hosts_payment_hook(self, url):
        with pytest.raises(ConfigError, match="PAYMENT_WEBHOOK_URL"):
            self.read(PAYMENT_WEBHOOK_URL=url, WEBHOOK_SECRET=SECRET)

    def test_the_secret_is_not_printed_with_the_settings(self):
        found = self.read(PAYMENT_WEBHOOK_URL=URL, WEBHOOK_SECRET=SECRET)
        assert SECRET not in repr(found)

    @pytest.mark.parametrize(
        ("given", "origin"),
        [
            ("https://chat.example/", "https://chat.example"),
            ("http://localhost:8901", "http://localhost:8901"),
        ],
    )
    def test_reads_the_hosts_public_origin(self, given, origin):
        assert self.read(HOST_PUBLIC_URL=given).host_public_url == origin

    @pytest.mark.parametrize("given", ["chat.example", "https://chat.example/c/1", "javascript:alert(1)"])
    def test_refuses_a_public_address_that_is_not_an_origin(self, given):
        with pytest.raises(ConfigError, match="HOST_PUBLIC_URL"):
            self.read(HOST_PUBLIC_URL=given)


async def checkout_of(stack):
    flow = stack.payments
    issued = await flow.create_quote(
        amount_kobo=250_000, amount_as_user_said="2500", description="Lunch", merchant="Demo Kitchen",
        merchant_ref=None, idempotency_key="hook-key-0000001",
    )  # fmt: skip
    approved = await flow.approve(issued.quote["id"], issued.approval_token, 250_000)
    return issued.quote["id"], approved["checkoutUrl"].rsplit("/", 1)[1]


def stack_with(notifier):
    stack = make_stack()
    object.__setattr__(stack.app, "notifier", notifier)
    return stack


class TestWhenTheCheckoutRecordsAPayment:
    @pytest.mark.parametrize("button", ["pay", "decline"])
    async def test_the_host_is_told_once_which_quote_moved(self, button):
        notifier = RecordingNotifier()
        stack = stack_with(notifier)
        quote_id, reference = await checkout_of(stack)
        await handle(stack.app, "POST", f"/sim/checkout/{reference}/{button}", {}, b"")
        await handle(stack.app, "POST", f"/sim/checkout/{reference}/{button}", {}, b"")
        assert notifier.moved == [quote_id]

    async def test_opening_or_closing_the_page_tells_nobody(self):
        notifier = RecordingNotifier()
        stack = stack_with(notifier)
        _, reference = await checkout_of(stack)
        await handle(stack.app, "GET", f"/sim/checkout/{reference}", {}, b"")
        await handle(stack.app, "POST", f"/sim/checkout/{reference}/close", {}, b"")
        assert notifier.moved == []

    async def test_a_press_from_another_origin_tells_nobody(self):
        notifier = RecordingNotifier()
        stack = stack_with(notifier)
        _, reference = await checkout_of(stack)
        await handle(
            stack.app, "POST", f"/sim/checkout/{reference}/pay", {"origin": "https://evil.example"}, b""
        )
        assert notifier.moved == []

    async def test_a_reference_this_server_did_not_make_for_a_quote_tells_nobody(self):
        notifier = RecordingNotifier()
        stack = stack_with(notifier)
        api = stack.app.contexts["paystack-pay"].paystack
        from checkout.paystack.api import CheckoutRequest

        await api.initialize_transaction(
            CheckoutRequest(100_000, "a@example.com", "ref-loose-1", "qt-1", "x")
        )
        await handle(stack.app, "POST", "/sim/checkout/ref-loose-1/pay", {}, b"")
        assert notifier.moved == []


class TestAWebhookThatFailsNeverBreaksThePayment:
    @pytest.mark.parametrize(
        "failure",
        [TransportError("fetch failed"), RuntimeError("bug"), Reply(500, "boom", None)],
        ids=["no connection", "a bug", "host error"],
    )
    async def test_the_payment_is_recorded_and_the_receipt_is_reached_by_polling(self, failure):
        webhook, lines = hook(ScriptedTransport(lambda _: failure))
        stack = stack_with(webhook)
        quote_id, reference = await checkout_of(stack)
        page = await handle(stack.app, "POST", f"/sim/checkout/{reference}/pay", {}, b"")
        assert page.status == 200 and "Paid" in page.body
        assert any(json.loads(line)["event"].startswith("webhook.") for line in lines)
        view = await stack.payments.verify(quote_id)
        assert (view["phase"], view["receipt"]["title"]) == ("succeeded", "Payment received")

    async def test_a_host_that_never_answers_does_not_hold_the_page_for_long(self):
        class Silent:
            async def send(self, *_, **__):
                await asyncio.sleep(30)

        webhook, _ = hook(Silent(), timeout=0.05)
        stack = stack_with(webhook)
        _, reference = await checkout_of(stack)
        page = await asyncio.wait_for(handle(stack.app, "POST", f"/sim/checkout/{reference}/pay", {}, b""), 2)
        assert page.status == 200 and "Paid" in page.body
