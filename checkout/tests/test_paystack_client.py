# SPDX-License-Identifier: AGPL-3.0-or-later
"""The real Paystack client on a scripted transport, ported from the TypeScript demo's client.test.ts."""

import pytest

from checkout.paystack.api import (
    AccountLookup,
    CheckoutRequest,
    PaystackError,
    RecipientRequest,
    TransferRequest,
)
from checkout.paystack.client import PaystackClient
from checkout.transport import Reply, TransportError
from tests.keys import fake_key
from tests.support import ScriptedTransport, json_reply

KEY = fake_key("test", "unittestkey0001")


def client_with(answer):
    transport = ScriptedTransport(answer)
    return PaystackClient(KEY, transport), transport


def test_refuses_a_live_key():
    with pytest.raises(ValueError, match="test secret key"):
        PaystackClient(fake_key("live"), ScriptedTransport(lambda _: None))


async def test_initialize_posts_the_amount_in_kobo_as_a_string_with_the_reference_and_a_bearer_key():
    client, transport = client_with(
        lambda _: json_reply(
            {
                "status": True,
                "message": "Authorization URL created",
                "data": {
                    "authorization_url": "https://checkout.paystack.com/accesscodeone",
                    "access_code": "accesscodeone",
                    "reference": "qt-1-a1",
                },
            }
        )
    )
    checkout = await client.initialize_transaction(
        CheckoutRequest(250_000, "demo@example.com", "qt-1-a1", "qt-1", "Lunch")
    )
    assert (checkout.authorization_url, checkout.access_code, checkout.reference) == (
        "https://checkout.paystack.com/accesscodeone",
        "accesscodeone",
        "qt-1-a1",
    )
    sent = transport.calls[0]
    assert (sent.url, sent.method) == ("https://api.paystack.co/transaction/initialize", "POST")
    assert sent.headers["authorization"] == f"Bearer {KEY}"
    assert sent.body["amount"] == "250000" and sent.body["currency"] == "NGN"
    assert sent.body["email"] == "demo@example.com" and sent.body["reference"] == "qt-1-a1"
    import json

    assert json.loads(sent.body["metadata"])["quote_id"] == "qt-1"


async def test_verify_reads_status_amount_and_currency_from_the_data_object_not_the_envelope():
    client, transport = client_with(
        lambda _: json_reply(
            {
                "status": True,
                "message": "Verification successful",
                "data": {
                    "id": 4099260516,
                    "status": "success",
                    "reference": "qt-1-a1",
                    "amount": 250000,
                    "currency": "NGN",
                    "gateway_response": "Successful",
                    "paid_at": "2026-09-29T09:15:02.000Z",
                    "authorization": {"last4": "4081", "bin": "408408", "card_type": "visa "},
                },
            }
        )
    )
    check = await client.verify_transaction("qt-1-a1")
    assert (check.status, check.reference, check.amount_kobo, check.currency) == (
        "success",
        "qt-1-a1",
        250_000,
        "NGN",
    )
    assert (check.gateway_response, check.paid_at) == ("Successful", "2026-09-29T09:15:02.000Z")
    assert "4081" not in repr(check)
    assert transport.calls[0].url == "https://api.paystack.co/transaction/verify/qt-1-a1"
    assert transport.calls[0].method == "GET"


@pytest.mark.parametrize(
    "status", ["abandoned", "failed", "ongoing", "pending", "processing", "queued", "reversed"]
)
async def test_every_documented_transaction_status_is_accepted(status):
    client, _ = client_with(
        lambda _: json_reply(
            {"status": True, "data": {"status": status, "reference": "r", "amount": 1, "currency": "NGN"}}
        )
    )
    assert (await client.verify_transaction("r")).status == status


async def test_an_account_is_resolved_with_the_query_in_the_url():
    client, transport = client_with(
        lambda _: json_reply(
            {"status": True, "data": {"account_number": "0000000000", "account_name": "PAYSTACK TEST"}}
        )
    )
    assert await client.resolve_account(AccountLookup("0000000000", "057")) == "PAYSTACK TEST"
    assert (
        transport.calls[0].url
        == "https://api.paystack.co/bank/resolve?account_number=0000000000&bank_code=057"
    )


async def test_a_nuban_recipient_is_created():
    client, transport = client_with(
        lambda _: json_reply(
            {
                "status": True,
                "data": {
                    "recipient_code": "RCP_m7ljkv8leesep7p",
                    "name": "Tolu Robert",
                    "details": {
                        "account_number": "0100000001",
                        "bank_code": "058",
                        "bank_name": "Guaranty Trust Bank",
                    },
                },
            }
        )
    )
    recipient = await client.create_recipient(RecipientRequest("Tolu Robert", "0100000001", "058"))
    assert (recipient.recipient_code, recipient.name, recipient.bank_name) == (
        "RCP_m7ljkv8leesep7p",
        "Tolu Robert",
        "Guaranty Trust Bank",
    )
    assert transport.calls[0].body == {
        "type": "nuban",
        "name": "Tolu Robert",
        "account_number": "0100000001",
        "bank_code": "058",
        "currency": "NGN",
    }


async def test_a_recipient_without_a_bank_name_is_an_unknown_bank():
    client, _ = client_with(
        lambda _: json_reply({"status": True, "data": {"recipient_code": "RCP_1", "name": "N"}})
    )
    assert (
        await client.create_recipient(RecipientRequest("N", "0100000001", "058"))
    ).bank_name == "Unknown bank"


TRANSFER_DATA = {
    "status": "success",
    "transfer_code": "TRF_v5tip3zx8nna9o78",
    "reference": "trf-qt-0000000000000001",
    "amount": 100000,
}


async def test_a_transfer_is_initiated_from_the_balance_with_an_integer_amount():
    client, transport = client_with(
        lambda _: json_reply({"status": True, "message": "queued", "data": TRANSFER_DATA})
    )
    outcome = await client.initiate_transfer(
        TransferRequest(100_000, "RCP_x", "trf-qt-0000000000000001", "Bonus")
    )
    assert (outcome.status, outcome.transfer_code, outcome.reference, outcome.amount_kobo) == (
        "success",
        "TRF_v5tip3zx8nna9o78",
        "trf-qt-0000000000000001",
        100_000,
    )
    assert transport.calls[0].body == {
        "source": "balance",
        "amount": 100_000,
        "recipient": "RCP_x",
        "reference": "trf-qt-0000000000000001",
        "reason": "Bonus",
    }


async def test_a_transfer_is_finalized_with_the_code_and_otp_and_verified_by_reference():
    client, transport = client_with(
        lambda _: json_reply(
            {
                "status": True,
                "data": {
                    "status": "pending",
                    "transfer_code": "TRF_1",
                    "reference": "trf-ref-0000000000001",
                    "amount": 5,
                },
            }
        )
    )
    await client.finalize_transfer("TRF_1", "928783")
    await client.verify_transfer("trf-ref-0000000000001")
    assert transport.calls[0].url == "https://api.paystack.co/transfer/finalize_transfer"
    assert transport.calls[0].body == {"transfer_code": "TRF_1", "otp": "928783"}
    assert transport.calls[1].url == "https://api.paystack.co/transfer/verify/trf-ref-0000000000001"


@pytest.mark.parametrize("status", ["otp", "reversed", "failed"])
async def test_otp_reversed_and_failed_transfer_statuses_are_accepted(status):
    client, _ = client_with(
        lambda _: json_reply(
            {"status": True, "data": {"status": status, "transfer_code": "T", "reference": "r", "amount": 1}}
        )
    )
    assert (await client.verify_transfer("r")).status == status


async def test_a_4xx_is_a_final_error_with_paystacks_message():
    client, _ = client_with(
        lambda _: json_reply({"status": False, "message": "Duplicate Transaction Reference"}, 400)
    )
    with pytest.raises(PaystackError) as refused:
        await client.verify_transaction("r")
    assert (str(refused.value), refused.value.retryable, refused.value.http_status) == (
        "Duplicate Transaction Reference",
        False,
        400,
    )


@pytest.mark.parametrize("status", [500, 502, 429])
async def test_a_server_error_or_rate_limit_is_worth_retrying(status):
    client, _ = client_with(lambda _: json_reply({"status": False, "message": "busy"}, status))
    with pytest.raises(PaystackError) as refused:
        await client.verify_transaction("r")
    assert (refused.value.retryable, refused.value.http_status) == (True, status)


async def test_a_network_failure_is_worth_retrying():
    client, _ = client_with(lambda _: TransportError("socket hang up"))
    with pytest.raises(PaystackError) as refused:
        await client.verify_transaction("r")
    assert refused.value.retryable


async def test_a_200_whose_envelope_says_the_call_failed_is_refused():
    client, _ = client_with(lambda _: json_reply({"status": False, "message": "Nope", "data": None}))
    with pytest.raises(PaystackError) as refused:
        await client.verify_transaction("r")
    assert (str(refused.value), refused.value.retryable) == ("Nope", False)


async def test_a_reply_that_is_not_json_is_refused():
    client, _ = client_with(lambda _: Reply(200, "<html>gateway</html>"))
    with pytest.raises(PaystackError, match="could not read"):
        await client.verify_transaction("r")


@pytest.mark.parametrize(
    "data",
    [
        {"status": "success"},
        {"status": "vanished", "reference": "r", "amount": 1, "currency": "NGN"},
        {"status": "success", "reference": "r", "amount": "250000", "currency": "NGN"},
    ],
)
async def test_data_without_the_expected_shape_is_refused(data):
    client, _ = client_with(lambda _: json_reply({"status": True, "data": data}))
    with pytest.raises(PaystackError, match="expected shape"):
        await client.verify_transaction("r")


async def test_the_key_is_never_in_an_error():
    client, _ = client_with(lambda _: json_reply({"status": False, "message": "Invalid key"}, 401))
    with pytest.raises(PaystackError) as refused:
        await client.verify_transaction("r")
    assert KEY not in repr(refused.value) + str(refused.value)


async def test_a_reference_is_escaped_in_the_path():
    client, transport = client_with(lambda _: json_reply({"status": False, "message": "x"}, 400))
    with pytest.raises(PaystackError):
        await client.verify_transaction("a/b?c")
    assert transport.calls[0].url.endswith("/transaction/verify/a%2Fb%3Fc")
