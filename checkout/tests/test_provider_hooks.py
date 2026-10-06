# SPDX-License-Identifier: AGPL-3.0-or-later
"""What a provider's webhook does: Paystack's must carry its signature, VTpass's is only a hint, and
either makes the connector check the quote it names again, as that quote's owner, if it is still
pending. The simulated checkout announces a payment the same way. Every minute, pending quotes are
checked again and overdue ones expire, so their endings are events though nobody is looking."""

import json

import pytest

from checkout.background import HostRouted
from checkout.config import Settings
from checkout.errors import ConfigError
from checkout.http import handle
from checkout.ids import new_quote_id, transaction_reference
from checkout.provider_hooks import paystack
from checkout.provider_hooks.references import quote_id_in
from checkout.sim_checkout import _press
from checkout.transport import Reply
from tests.connector_support import approve_args, key, quote_of
from tests.support import ALICE, BOB, ScriptedTransport, make_stack

PAY = "paystack-pay"
SECRET = "test-secret-not-real"


async def approved_for(stack, owner):
    made = await stack.call_as(
        owner, PAY, "create_payment_quote",
        amount_kobo=250_000, amount_as_user_said="2.5k", description="Lunch", merchant="Demo Kitchen",
        idempotency_key=key("hooks-owner"),
    )  # fmt: skip
    approved = await stack.call_as(owner, PAY, "approve_quote", **approve_args(made))
    return quote_of(made)["id"], quote_of(approved)["checkoutUrl"].rsplit("/", 1)[1]


async def state_of(stack, quote_id):
    return (await stack.db.row("SELECT state FROM quotes WHERE id = ?", quote_id))["state"]


def charge(reference, event="charge.success"):
    return json.dumps({"event": event, "data": {"reference": reference, "status": "success"}}).encode()


async def webhook(stack, body, signature=None):
    key_ = paystack.simulated_key(SECRET)
    given = paystack.sign(body, key_) if signature is None else signature
    return await handle(stack.app, "POST", "/hooks/paystack", {"x-paystack-signature": given}, body)


@pytest.fixture
def stack():
    return make_stack(approval_secret=SECRET)


def test_every_reference_the_connectors_make_names_its_quote():
    quote = new_quote_id()
    for reference in (transaction_reference(quote, 2), f"trf-{quote}", f"202610061230{quote}"):
        assert quote_id_in(reference) == quote
    assert quote_id_in("ref-loose-1") is None and quote_id_in(None) is None


def test_paystacks_signature_is_hmac_sha512_hex_of_the_raw_body():
    import hashlib
    import hmac

    body = b'{"event":"charge.success"}'
    assert paystack.sign(body, "sk_test_x") == hmac.new(b"sk_test_x", body, hashlib.sha512).hexdigest()


async def test_a_paid_checkout_ends_the_quote_with_nobody_asking(stack):
    quote, reference = await approved_for(stack, ALICE)
    await handle(stack.app, "POST", f"/sim/checkout/{reference}/pay", {}, b"")
    assert await state_of(stack, quote) == "approved", "the request only queues the check"
    await stack.run_jobs()
    assert await state_of(stack, quote) == "settled"


@pytest.mark.parametrize("button", ["decline", "close"])
async def test_a_declined_or_closed_checkout_announces_nothing(stack, button):
    quote, reference = await approved_for(stack, ALICE)
    await handle(stack.app, "POST", f"/sim/checkout/{reference}/{button}", {}, b"")
    await stack.run_jobs()
    assert await state_of(stack, quote) == "approved"


async def test_a_genuine_webhook_checks_the_quote_again_as_its_owner_and_no_other(stack):
    alices, alices_ref = await approved_for(stack, ALICE)
    bobs, bobs_ref = await approved_for(stack, BOB)
    await _press(stack.app, bobs_ref, "pay")
    await _press(stack.app, alices_ref, "pay")
    answer = await webhook(stack, charge(bobs_ref))
    assert answer.status == 200
    await stack.run_jobs()
    assert await state_of(stack, bobs) == "settled" and await state_of(stack, alices) == "approved"


@pytest.mark.parametrize("signature", ["", "0" * 128, paystack.sign(b"another body", "k")])
async def test_an_unsigned_or_wrongly_signed_paystack_webhook_is_refused(stack, signature):
    quote, reference = await approved_for(stack, ALICE)
    await _press(stack.app, reference, "pay")
    assert (await webhook(stack, charge(reference), signature)).status == 401
    await stack.run_jobs()
    assert await state_of(stack, quote) == "approved"


async def test_a_webhook_for_a_quote_that_is_not_pending_or_not_ours_does_nothing(stack):
    await webhook(stack, charge(transaction_reference(new_quote_id(), 1)))
    await webhook(stack, charge("ref-loose-1"))
    await webhook(stack, charge("x", event="subscription.create"))
    assert [json.loads(line)["event"] for line in stack.audit_lines].count("recheck.skipped") == 3


async def test_vtpass_is_answered_as_it_asks_and_its_hint_is_checked_like_any_other(stack):
    quote, reference = await approved_for(stack, ALICE)
    await _press(stack.app, reference, "pay")
    update = json.dumps(
        {"type": "transaction-update", "data": {"requestId": f"202610061230{quote}"}}
    ).encode()
    answer = await handle(stack.app, "POST", "/hooks/vtpass", {}, update)
    assert json.loads(answer.body) == {"response": "success"}
    await stack.run_jobs()
    assert await state_of(stack, quote) == "settled"


async def test_a_body_too_large_is_refused_before_it_is_read(stack):
    for provider in ("paystack", "vtpass"):
        answer = await handle(stack.app, "POST", f"/hooks/{provider}", {}, b"{" + b" " * 70_000 + b"}")
        assert answer.status == 413


async def test_the_minute_checks_pending_quotes_again_and_expires_overdue_ones(stack):
    paid, reference = await approved_for(stack, ALICE)
    await _press(stack.app, reference, "pay")
    left = quote_of(await stack.call_as(
        BOB, PAY, "create_payment_quote", amount_kobo=100_000, amount_as_user_said="1000", description="Tea",
        merchant="Demo Kitchen", idempotency_key=key("hooks-open"),
    ))["id"]  # fmt: skip
    stack.clock.advance(stack.app.settings.quote_ttl_seconds + 60)
    await stack.app.background.minute()
    await stack.run_jobs()
    assert await state_of(stack, paid) == "settled" and await state_of(stack, left) == "expired"


async def test_a_recheck_that_ends_a_quote_hands_its_event_on(stack):
    transport = ScriptedTransport(
        lambda sent: (
            Reply(200, json.dumps({"challenge": sent.body["challenge"]}))
            if sent.body.get("type") == "verification"
            else Reply(200, "{}")
        )
    )
    object.__setattr__(stack.app.background.events, "_transport", transport)
    object.__setattr__(stack.app.background.delivery, "_transport", transport)
    quote, reference = await approved_for(stack, ALICE)
    secret = "whsec_" + __import__("base64").b64encode(b"k" * 32).decode()
    await stack.app.background.events.subscribe(ALICE, PAY, {
        "name": "quote.finished", "arguments": {"quote_id": quote},
        "delivery": {"mode": "webhook", "url": "https://agent.example/events", "secret": secret},
    })  # fmt: skip
    await handle(stack.app, "POST", f"/sim/checkout/{reference}/pay", {}, b"")
    await stack.run_jobs()
    sent = [c.body for c in transport.calls if c.body.get("name") == "quote.finished"]
    assert len(sent) == 1 and sent[0]["data"]["state"] == "settled"


async def test_the_hosts_own_callbacks_go_through_its_binding_and_others_go_out():
    binding, other = (
        ScriptedTransport(lambda s: Reply(200, "b")),
        ScriptedTransport(lambda s: Reply(200, "o")),
    )
    routed = HostRouted("https://chat.example", binding, other)
    args = {"headers": {}, "body": "{}", "timeout_seconds": 1}
    await routed.send("POST", "https://chat.example/hooks/events", **args)
    await routed.send("POST", "https://agent.example/hooks/events", **args)
    await routed.send("POST", "https://chat.example.evil/hooks/events", **args)
    assert [c.url for c in binding.calls] == ["https://chat.example/hooks/events"]
    assert len(other.calls) == 2


class TestSettings:
    def read(self, **env):
        return Settings.from_env({"APPROVAL_SECRET": "x-not-real", **env}.get)

    def test_names_the_hosts_binding(self):
        assert self.read(HOST_BINDING="HOST").host_binding == "HOST"
        assert self.read().host_binding is None

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
