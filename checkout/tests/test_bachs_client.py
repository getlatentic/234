# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Bachs client (bachs/client.py) as it would talk to the sandbox, over a scripted transport (no call
reaches Bachs), and the simulator (bachs/sim.py) that stands in for it."""

import json

import pytest

from checkout.bachs.api import BachsError, CheckoutRequest, kobo_of, naira_text
from checkout.bachs.client import BachsClient, epoch_ms
from checkout.bachs.settings import BachsSettings
from checkout.bachs.sim import SIMULATED_KEY, BachsSimulator
from checkout.bachs.sim_store import BachsSimStore
from checkout.errors import DomainError
from checkout.sqlite_db import SqliteDb
from checkout.transport import TransportError
from checkout.wallet.topups import owner_tag
from tests.support import ALICE, FakeClock, ScriptedTransport, json_reply, make_stack
from tests.topup_support import SANDBOX_KEY, SECRET, SIMULATED, WEBHOOK_SECRET, balance, deliver, succeeded

CREATED = {
    "checkout_id": "chk_2N3o4P5q6R7s8T9u",
    "checkout_url": "https://checkout.bachs.io/c/V8xQ2mZpLj9RfTa",
    "status": "open",
    "expires_at": "2026-09-29T11:00:00Z",
    "created_at": "2026-09-29T10:00:00Z",
}


def request(**over) -> CheckoutRequest:
    return CheckoutRequest(**{"reference": "wt-0123456789abcdef0123", "amount_kobo": 500_050,
                              "expires_in_minutes": 60, **over})  # fmt: skip


def sandbox_stack(transport):
    settings = BachsSettings("sandbox", SANDBOX_KEY, WEBHOOK_SECRET)
    return make_stack(approval_secret=SECRET, bachs=settings, transport=transport)


def test_naira_text_and_kobo_round_trip_exactly():
    for kobo, text in ((1, "0.01"), (500_050, "5000.50"), (20_000_000, "200000.00")):
        assert naira_text(kobo) == text and kobo_of(text) == kobo
    for shape in ("5000", "5000.5", "5,000.00", "05000.00", "-1.00", " 1.00", "1.000", 100, None):
        assert kobo_of(shape) is None


def test_bachs_times_are_utc_with_or_without_the_offset():
    assert epoch_ms("2026-09-29T11:00:00Z") == epoch_ms("2026-09-29T11:00:00") == 1_790_679_600_000
    assert epoch_ms("2026-09-29T12:00:00.000+01:00") == 1_790_679_600_000


def test_only_a_sandbox_key_is_taken():
    for key in ("sk_" + "live_abc12345", "sk_" + "test_abc12345", ""):
        with pytest.raises(ValueError, match="sandbox"):
            BachsClient(key, ScriptedTransport(lambda sent: json_reply(CREATED)))


async def test_a_checkout_is_one_post_with_the_reference_as_its_idempotency_key():
    transport = ScriptedTransport(lambda sent: json_reply(CREATED, 201))
    client = BachsClient(SANDBOX_KEY, transport)
    made = await client.create_checkout(
        request(metadata={"wallet_owner": "tag"}, customer_email="payer@example.com")
    )
    [sent] = transport.calls
    assert (sent.method, sent.url) == ("POST", "https://sandbox-api.bachs.io/v1/checkout-sessions")
    assert sent.headers["authorization"] == f"Bearer {SANDBOX_KEY}"
    assert sent.headers["idempotency-key"] == "wt-0123456789abcdef0123"
    assert sent.body == {
        "pricing": {"currency": "NGN", "amount": "5000.50"},
        "reference": "wt-0123456789abcdef0123",
        "metadata": {"wallet_owner": "tag"},
        "expires_in_minutes": 60,
        "customer": {"email": "payer@example.com"},
    }
    assert (made.checkout_id, made.checkout_url, made.status) == (
        "chk_2N3o4P5q6R7s8T9u",
        "https://checkout.bachs.io/c/V8xQ2mZpLj9RfTa",
        "open",
    )
    assert made.expires_at == 1_790_679_600_000


@pytest.mark.parametrize(
    ("answer", "retryable", "message"),
    [
        (TransportError("timed out"), True, "could not be reached"),
        (json_reply({"detail": "Internal", "error_code": "INTERNAL"}, 500), True, "Internal"),
        (json_reply({"detail": "Slow down", "error_code": "RATE_LIMITED"}, 429), True, "Slow down"),
        (
            json_reply({"detail": "In flight", "error_code": "IDEMPOTENCY_IN_PROGRESS"}, 409),
            True,
            "In flight",
        ),
        (
            json_reply({"detail": "Other body", "error_code": "IDEMPOTENCY_CONFLICT"}, 409),
            False,
            "Other body",
        ),
        (json_reply({"detail": "Missing or invalid", "error_code": "UNAUTHORIZED"}, 401), False, "Missing"),
        (json_reply({"checkout_id": "chk_1"}, 201), False, "expected shape"),
        (json_reply({**CREATED, "expires_at": "soon"}, 201), False, "expected shape"),
    ],
)
async def test_a_failed_call_says_whether_the_same_request_may_be_sent_again(answer, retryable, message):
    client = BachsClient(SANDBOX_KEY, ScriptedTransport(lambda sent: answer))
    with pytest.raises(BachsError, match=message) as failed:
        await client.create_checkout(request())
    assert failed.value.retryable is retryable


class TestTheSimulator:
    @pytest.fixture
    def client(self):
        simulator = BachsSimulator(BachsSimStore(SqliteDb()), FakeClock(), "http://localhost:8787/sim/bachs/")
        return BachsClient(SIMULATED_KEY, simulator), simulator

    async def test_answers_a_checkout_in_the_documented_shape(self, client):
        made = await client[0].create_checkout(request())
        assert made.checkout_url == f"http://localhost:8787/sim/bachs/{made.checkout_id}"
        assert made.status == "open" and made.expires_at == FakeClock().now() + 3_600_000

    async def test_answers_a_repeated_idempotency_key_with_the_first_checkout(self, client):
        first = await client[0].create_checkout(request())
        assert await client[0].create_checkout(request()) == first

    async def test_refuses_a_key_reused_with_another_body(self, client):
        await client[0].create_checkout(request())
        with pytest.raises(BachsError, match="another body"):
            await client[0].create_checkout(request(amount_kobo=1))

    async def test_refuses_a_reference_used_before_under_another_key(self, client):
        await client[0].create_checkout(request())
        reply = await client[1].send(
            "POST",
            "https://sandbox-api.bachs.io/v1/checkout-sessions",
            headers={"Authorization": f"Bearer {SIMULATED_KEY}", "Idempotency-Key": "other"},
            body=json.dumps(request().body()),
            timeout_seconds=1,
        )
        assert reply.status == 400 and "already used" in reply.body

    @pytest.mark.parametrize(
        "body",
        [
            {"pricing": {"currency": "USD", "amount": "1.00"}, "reference": "r"},
            {"pricing": {"currency": "NGN", "amount": "0.00"}, "reference": "r"},
            {"pricing": {"currency": "NGN", "amount": 100}, "reference": "r"},
            {"pricing": {"currency": "NGN", "amount": "1.00"}, "reference": "r" * 129},
            {"pricing": {"currency": "NGN", "amount": "1.00"}, "reference": "r", "expires_in_minutes": 1441},
            {"pricing": {"currency": "NGN", "amount": "1.00"}, "reference": "r", "metadata": []},
        ],
    )
    async def test_refuses_what_bachs_documents_as_invalid(self, client, body):
        reply = await client[1].send(
            "POST", "https://sandbox-api.bachs.io/v1/checkout-sessions",
            headers={"Authorization": f"Bearer {SIMULATED_KEY}"}, body=json.dumps(body), timeout_seconds=1,
        )  # fmt: skip
        assert reply.status == 400 and json.loads(reply.body)["error_code"] == "VALIDATION_ERROR"

    async def test_refuses_any_key_but_a_sandbox_one(self, client):
        reply = await client[1].send(
            "POST", "https://sandbox-api.bachs.io/v1/checkout-sessions",
            headers={"Authorization": "Bearer sk_" + "live_x"}, body="{}", timeout_seconds=1,
        )  # fmt: skip
        assert reply.status == 401


class TestSandboxMode:
    async def test_a_top_up_asks_the_sandbox_and_its_webhook_secret_is_the_endpoints(self):
        transport = ScriptedTransport(lambda sent: json_reply(CREATED, 201))
        stack = sandbox_stack(transport)
        topups = stack.app.funding.topups
        await topups.journal.open(ALICE)
        topup = await topups.start(ALICE, 500_000)
        [sent] = transport.calls
        assert sent.url == "https://sandbox-api.bachs.io/v1/checkout-sessions"
        assert sent.headers["idempotency-key"] == topup.id
        assert sent.body["metadata"] == {"wallet_topup": topup.id, "wallet_owner": owner_tag(ALICE)}
        assert sent.body["customer"] == {"email": "demo.payer@example.com"}
        assert topup.provider_ref == CREATED["checkout_id"] and topup.expires_at == 1_790_679_600_000
        assert stack.app.funding.sim is None
        assert (await deliver(stack, succeeded(topup), (SIMULATED,))).status == 400
        assert (await deliver(stack, succeeded(topup), (WEBHOOK_SECRET,))).status == 200
        assert await balance(stack) == 500_000

    async def test_a_checkout_bachs_could_not_make_leaves_the_top_up_expired(self):
        stack = sandbox_stack(ScriptedTransport(lambda sent: TransportError("timed out")))
        topups = stack.app.funding.topups
        await topups.journal.open(ALICE)
        with pytest.raises(DomainError) as refused:
            await topups.start(ALICE, 500_000)
        assert refused.value.code == "TOPUP_UNAVAILABLE"
        [row] = await stack.rows("SELECT state, provider_ref, checkout_url FROM wallet_topup")
        assert row == {"state": "expired", "provider_ref": None, "checkout_url": None}

    async def test_a_top_up_with_no_checkout_is_credited_by_no_collection(self):
        stack = sandbox_stack(ScriptedTransport(lambda sent: TransportError("timed out")))
        topups = stack.app.funding.topups
        await topups.journal.open(ALICE)
        with pytest.raises(DomainError):
            await topups.start(ALICE, 500_000)
        [row] = await stack.rows("SELECT id FROM wallet_topup")
        topup = await topups.get(row["id"])
        assert (await deliver(stack, succeeded(topup, checkout_id=None), (WEBHOOK_SECRET,))).status == 200
        assert await balance(stack) == 0

    async def test_the_payer_is_sent_back_only_to_a_public_https_chat(self):
        transport = ScriptedTransport(lambda sent: json_reply(CREATED, 201))
        settings = BachsSettings("sandbox", SANDBOX_KEY, WEBHOOK_SECRET)
        stack = make_stack(
            approval_secret=SECRET,
            bachs=settings,
            transport=transport,
            host_public_url="https://chat.example",
        )
        await stack.app.funding.topups.journal.open(ALICE)
        await stack.app.funding.topups.start(ALICE, 100_000)
        assert transport.calls[0].body["success_url"] == "https://chat.example"
