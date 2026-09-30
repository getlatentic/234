# SPDX-License-Identifier: AGPL-3.0-or-later
"""The VTpass client on a scripted transport, ported from the TypeScript demo's client.test.ts."""

import pytest

from checkout.transport import Reply, TransportError
from checkout.vtpass.api import AirtimeOrder, DataOrder, VtpassError
from checkout.vtpass.client import VtpassClient, VtpassCredentials, describe_reply
from tests.support import FakeClock, ScriptedTransport, json_reply

CREDENTIALS = VtpassCredentials("api-key-value", "PK_public_value", "SK_secret_value")
DELIVERED = {
    "code": "000",
    "response_description": "TRANSACTION SUCCESSFUL",
    "content": {
        "transactions": {
            "status": "delivered",
            "product_name": "MTN Airtime VTU",
            "unique_element": "08011111111",
        }
    },
    "requestId": "202609291405abc",
}
ORDER = AirtimeOrder("r-1234567890123", "mtn", "08011111111", 10_000)


def client_with(answer, **options):
    transport = ScriptedTransport(answer)
    return VtpassClient(CREDENTIALS, transport, clock=FakeClock(), **options), transport


def refused():
    return json_reply("Invalid Credentials.", 401)


class TestAirtimePurchase:
    async def test_posts_to_the_sandbox_with_the_api_and_secret_keys_and_the_documented_fields(self):
        client, transport = client_with(lambda _: json_reply(DELIVERED))
        outcome = await client.buy_airtime(AirtimeOrder("202609291405abc", "9mobile", "08011111111", 50_000))
        assert (outcome.status, outcome.code) == ("delivered", "000")
        sent = transport.calls[0]
        assert (sent.url, sent.method) == ("https://sandbox.vtpass.com/api/pay", "POST")
        assert sent.headers["api-key"] == "api-key-value"
        assert sent.headers["secret-key"] == "SK_secret_value"
        assert "public-key" not in sent.headers
        assert sent.body == {
            "request_id": "202609291405abc",
            "serviceID": "etisalat",
            "amount": 500,
            "phone": "08011111111",
        }

    @pytest.mark.parametrize(
        ("network", "service"),
        [("mtn", "mtn"), ("airtel", "airtel"), ("glo", "glo"), ("9mobile", "etisalat")],
    )
    async def test_uses_the_service_id_of_each_network(self, network, service):
        client, transport = client_with(lambda _: json_reply(DELIVERED))
        await client.buy_airtime(AirtimeOrder("r-1234567890123", network, "08011111111", 10_000))
        assert transport.calls[0].body["serviceID"] == service

    async def test_a_dropped_connection_is_pending_never_failed(self):
        client, _ = client_with(lambda _: TransportError("fetch failed"))
        outcome = await client.buy_airtime(ORDER)
        assert (outcome.status, outcome.code) == ("pending", None)

    async def test_a_page_that_is_not_json_is_pending(self):
        client, _ = client_with(lambda _: Reply(502, "<html>502</html>"))
        assert (await client.buy_airtime(ORDER)).status == "pending"

    async def test_a_documented_failure_code_is_failed(self):
        client, _ = client_with(
            lambda _: json_reply({"code": "018", "response_description": "LOW WALLET BALANCE"})
        )
        outcome = await client.buy_airtime(ORDER)
        assert (outcome.status, outcome.description) == ("failed", "LOW WALLET BALANCE")

    async def test_a_fractional_naira_amount_is_sent_as_a_decimal(self):
        client, transport = client_with(lambda _: json_reply(DELIVERED))
        await client.buy_airtime(AirtimeOrder("r-1234567890123", "mtn", "08011111111", 10_050))
        assert transport.calls[0].body["amount"] == 100.5


class TestDataPurchase:
    async def test_sends_the_phone_as_billers_code_with_the_variation_code(self):
        client, transport = client_with(lambda _: json_reply(DELIVERED))
        await client.buy_data(DataOrder("r-1234567890123", "mtn", "08011111111", "mtn-10mb-100", 10_000))
        assert transport.calls[0].body == {
            "request_id": "r-1234567890123",
            "serviceID": "mtn-data",
            "billersCode": "08011111111",
            "variation_code": "mtn-10mb-100",
            "amount": 100,
            "phone": "08011111111",
        }


class TestRequery:
    async def test_posts_the_request_id(self):
        client, transport = client_with(lambda _: json_reply(DELIVERED))
        assert (await client.requery("202609291405abc")).status == "delivered"
        assert transport.calls[0].url == "https://sandbox.vtpass.com/api/requery"
        assert transport.calls[0].body == {"request_id": "202609291405abc"}

    async def test_flags_a_request_id_vtpass_never_saw(self):
        client, _ = client_with(
            lambda _: json_reply({"code": "015", "response_description": "INVALID REQUEST ID"})
        )
        outcome = await client.requery("x")
        assert (outcome.status, outcome.unknown_request) == ("pending", True)


PLANS_REPLY = {
    "response_description": "000",
    "content": {
        "ServiceName": "MTN Data",
        "serviceID": "mtn-data",
        "variations": [
            {
                "variation_code": "mtn-10mb-100",
                "name": "N100 100MB - 24 hrs",
                "variation_amount": "100.00",
                "fixedPrice": "Yes",
            },
            {
                "variation_code": "mtn-open",
                "name": "Open price",
                "variation_amount": "0.00",
                "fixedPrice": "No",
            },
        ],
    },
}


class TestDataPlans:
    async def test_uses_get_with_the_api_and_public_keys_and_keeps_fixed_price_plans_in_kobo(self):
        client, transport = client_with(lambda _: json_reply(PLANS_REPLY))
        plans = await client.data_plans("mtn")
        assert [(p.code, p.name, p.amount_kobo) for p in plans] == [
            ("mtn-10mb-100", "N100 100MB - 24 hrs", 10_000)
        ]
        sent = transport.calls[0]
        assert sent.url == "https://sandbox.vtpass.com/api/service-variations?serviceID=mtn-data"
        assert sent.method == "GET"
        assert sent.headers["public-key"] == "PK_public_value"
        assert "secret-key" not in sent.headers

    async def test_a_reply_without_plans_is_refused(self):
        client, _ = client_with(lambda _: json_reply({"code": "012"}))
        with pytest.raises(VtpassError):
            await client.data_plans("mtn")

    async def test_no_reply_at_all_is_refused_too(self):
        client, _ = client_with(lambda _: TransportError("down"))
        with pytest.raises(VtpassError):
            await client.data_plans("mtn")


class TestAnAccountVtpassWillNotAccept:
    """HTTP 401, observed on the real sandbox 2026-09-29."""

    async def test_a_purchase_is_a_failure_with_a_plain_reason_not_a_pending_order(self):
        client, _ = client_with(lambda _: refused())
        outcome = await client.buy_airtime(ORDER)
        assert (outcome.status, outcome.code) == ("failed", "401")
        assert "refused the credentials" in outcome.description

    async def test_a_requery_is_a_failure_too(self):
        client, _ = client_with(lambda _: refused())
        assert (await client.requery("202609291105abc")).status == "failed"


BALANCE = {"code": 1, "contents": {"balance": 1081.82}}


class TestCheckAccess:
    async def test_asks_for_the_wallet_balance_with_the_api_and_public_keys_and_reads_it_in_kobo(self):
        client, transport = client_with(lambda _: json_reply(BALANCE))
        access = await client.check_access()
        assert (access.ok, access.balance_kobo) == (True, 108_182)
        sent = transport.calls[0]
        assert (sent.url, sent.method) == ("https://sandbox.vtpass.com/api/balance", "GET")
        assert sent.headers["public-key"] == "PK_public_value"
        assert "secret-key" not in sent.headers

    async def test_says_when_the_credentials_are_refused_and_does_not_remember_that(self):
        client, transport = client_with(lambda _: refused())
        access = await client.check_access()
        assert (access.ok, access.reason) == (False, "VTpass refused this account's credentials (HTTP 401).")
        await client.check_access()
        assert len(transport.calls) == 2

    async def test_remembers_a_good_answer_for_a_minute(self):
        clock = FakeClock()
        transport = ScriptedTransport(lambda _: json_reply(BALANCE))
        client = VtpassClient(CREDENTIALS, transport, clock=clock)
        await client.check_access()
        clock.advance(59)
        await client.check_access()
        assert len(transport.calls) == 1
        clock.advance(2)
        await client.check_access()
        assert len(transport.calls) == 2

    async def test_says_when_vtpass_cannot_be_reached(self):
        client, _ = client_with(lambda _: TransportError("fetch failed"))
        assert (await client.check_access()).reason == "VTpass could not be reached."

    async def test_says_when_vtpass_sends_no_balance(self):
        client, _ = client_with(lambda _: json_reply({"code": "012"}))
        assert (await client.check_access()).reason == "VTpass did not return a wallet balance."


class TestDebugOutput:
    def test_describes_a_reply_with_status_content_type_length_and_a_short_redacted_body(self):
        import json

        body = json.dumps({"code": "000", "transactionId": "17415980564672211596777904", "note": "x" * 400})
        line = describe_reply(200, "application/json", body)
        assert line.startswith("vtpass reply: HTTP 200 content-type=application/json length=")
        assert "[redacted]" in line
        assert "17415980564672211596777904" not in line
        assert len(line) < 420

    def test_says_none_when_there_is_no_content_type(self):
        assert (
            describe_reply(502, None, "Bad gateway")
            == "vtpass reply: HTTP 502 content-type=none length=11 body=Bad gateway"
        )

    async def test_is_off_unless_asked_for_and_when_on_logs_one_line_per_reply_and_nothing_about_the_request(
        self,
    ):
        quiet, _ = client_with(lambda _: refused())
        await quiet.buy_airtime(ORDER)
        lines: list[str] = []
        loud, _ = client_with(lambda _: refused(), debug=lines.append)
        await loud.buy_airtime(ORDER)
        assert lines == [
            'vtpass reply: HTTP 401 content-type=application/json length=22 body="Invalid Credentials."'
        ]
        assert "SK_secret_value" not in "".join(lines)
        assert "08011111111" not in "".join(lines)
