# SPDX-License-Identifier: AGPL-3.0-or-later
"""Reading what Index answers without guessing: numbers under the names its prose uses, a status word it names
or does not, the merchants 234 can buy from, a PKCE challenge as RFC 7636 gives it, and metadata that names an
address 234 does not send tokens to."""

import json
from typing import ClassVar

import pytest

from checkout.commerce.index.naming import disco_of, kind_of, network_of
from checkout.commerce.index.oauth import IndexOAuth, challenge_of
from checkout.commerce.index.outcomes import decided, named, placed
from checkout.commerce.index.purchase import Purchase
from checkout.commerce.index.reading import flat, kobo_in, whole_naira
from checkout.commerce.index.wire import IndexMisread, ToolReply, message_of, sse_messages
from checkout.errors import DomainError
from checkout.transport import Reply
from tests.support import FakeClock


class TestNumbers:
    def test_kobo_or_naira_at_the_top_or_in_a_section(self):
        assert kobo_in({"total_kobo": 960_000}, "total") == 960_000
        assert kobo_in({"total_naira": 9_600}, "total") == 960_000
        assert kobo_in({"total_naira": 9_600.5}, "total") == 960_050
        assert kobo_in(flat({"breakdown": {"grand_total_kobo": 5}}), "grand_total") == 5

    @pytest.mark.parametrize(
        "data", [{}, {"total": 5}, {"total_kobo": -1}, {"total_kobo": True}, {"total_kobo": "9"}]
    )
    def test_a_number_it_cannot_read_is_none_not_a_guess(self, data):
        assert kobo_in(data, "total") is None

    def test_a_field_at_the_top_beats_the_same_field_in_a_section(self):
        assert flat({"status": "a", "preview": {"status": "b", "x": 1}}) == {
            "status": "a",
            "x": 1,
            "preview": {"status": "b", "x": 1},
        }

    def test_index_takes_whole_naira_only(self):
        assert whole_naira(500_000) == 5_000
        with pytest.raises(DomainError):
            whole_naira(500_050)


class TestStatusWords:
    @pytest.mark.parametrize(
        ("word", "kind"),
        [
            ("success", "delivered"),
            ("Completed", "delivered"),
            ("in-progress", "pending"),
            ("PENDING", "pending"),
            ("failed", "failed"),
            ("needs_confirmation", "failed"),
            ("refunded", "failed"),
            ("purple", None),
            ("", None),
            (None, None),
        ],
    )  # fmt: skip
    def test_a_word_is_delivered_pending_or_failed_or_not_known(self, word, kind):
        assert named(word) == kind

    def test_a_word_it_does_not_know_is_pending_never_delivered(self):
        assert decided({"status": "purple"}, "status") == "pending"
        assert decided({"status": "success"}, "status") == "delivered"
        assert decided({}, "status") == "delivered"

    def test_a_payment_still_pending_keeps_a_placed_order_pending(self):
        purchase = Purchase("food", "order", {}, two_phase=True)
        reply = ToolReply("", {"status": "confirmed", "payment_status": "pending", "order_id": "o1"}, False)
        outcome = placed(purchase, reply)
        assert outcome.status == "pending" and ("Order", "o1") in outcome.receipt_lines

    def test_an_error_is_a_failure_in_indexs_words_on_one_line(self):
        purchase = Purchase("airtime", "quick_buy", {}, two_phase=False)
        outcome = placed(purchase, ToolReply("Not enough\nZap‮", {}, True))
        assert (
            outcome.status == "failed"
            and "Not enough Zap" in outcome.description
            and "\n" not in outcome.description
        )

    def test_a_prepaid_token_is_found_in_the_text_when_the_data_lacks_it(self):
        purchase = Purchase("electricity", "quick_buy", {"meter_type": "prepaid"}, two_phase=True)
        outcome = placed(
            purchase, ToolReply("Done. Token: 1234 5678 9012 3456 7890", {"status": "success"}, False)
        )
        assert ("Prepaid token", "1234 5678 9012 3456 7890") in outcome.receipt_lines

    def test_a_postpaid_meter_has_no_token_line(self):
        purchase = Purchase("electricity", "quick_buy", {"meter_type": "postpaid"}, two_phase=True)
        assert not [
            k
            for k, _ in placed(purchase, ToolReply("", {"status": "success"}, False)).receipt_lines
            if k == "Prepaid token"
        ]


class TestNamesIndexGivesItsMerchants:
    @pytest.mark.parametrize(
        ("index_id", "name", "category", "expected"),
        [
            ("chowdeck", "Chowdeck", "food", ("food", None)),
            ("mtn-airtime", "MTN Airtime", "airtime", ("airtime", "MTN")),
            ("9mobile-airtime", "9mobile", "airtime", ("airtime", "9MOBILE")),
            ("etisalat", "Etisalat Airtime", "airtime", ("airtime", "9MOBILE")),
            ("ikeja-electric", "Ikeja Electric", "bills", ("electricity", "ikeja")),
            ("phed", "Port Harcourt Electricity", "bills", ("electricity", "phed")),
            ("zap", "Zap", "transfers", None),
            ("mtn-data", "MTN Data", "data", None),
            ("some-shop", "A Shop", "ecommerce", None),
            ("pigeon", "Pigeon Airtime", "airtime", None),
            ("burger", "Burger", "food", None),
        ],
    )
    def test_the_kind_and_the_code_of_a_merchant(self, index_id, name, category, expected):
        assert kind_of(index_id, name, category) == expected

    def test_a_network_is_a_whole_word(self):
        assert network_of("glossy-airtime", "Glossy") is None and network_of("glo-airtime", "Glo") == "GLO"

    def test_a_distribution_company_is_found_by_its_name(self):
        assert disco_of("x", "Abuja Electricity Distribution") == "aedc" and disco_of("x", "Nowhere") is None


class TestThePkceChallenge:
    def test_is_the_s256_challenge_of_rfc_7636(self):
        assert (
            challenge_of("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk")
            == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
        )


class Serves:
    """A transport that answers every request with the same metadata."""

    def __init__(self, metadata):
        self.metadata = metadata

    async def send(self, method, url, *, headers, body, timeout_seconds):
        return Reply(200, json.dumps(self.metadata), "application/json")


class TestTheMetadataIsTrustedOnlyForIndexsOwnHosts:
    GOOD: ClassVar[dict[str, str]] = {
        "authorization_endpoint": "https://index.paystack.com/oauth/authorize",
        "token_endpoint": "https://index.mcp.paystack.africa/oauth/token",
        "registration_endpoint": "https://index.mcp.paystack.africa/oauth/register",
    }
    TRUSTED = frozenset({"https://index.paystack.com", "https://index.mcp.paystack.africa"})

    def oauth(self, metadata):
        return IndexOAuth(
            Serves(metadata), "https://index.mcp.paystack.africa/.well-known/x", self.TRUSTED, FakeClock()
        )

    async def test_takes_the_published_endpoints(self):
        found = await self.oauth(self.GOOD).endpoints()
        assert found.token.endswith("/oauth/token") and found.revocation is None

    @pytest.mark.parametrize(
        "key", ["authorization_endpoint", "token_endpoint", "registration_endpoint", "revocation_endpoint"]
    )
    async def test_refuses_an_endpoint_on_another_host(self, key):
        poisoned = {**self.GOOD, key: "https://evil.example/oauth"}
        with pytest.raises(IndexMisread):
            await self.oauth(poisoned).endpoints()

    async def test_refuses_a_plain_http_endpoint_on_the_right_host(self):
        with pytest.raises(IndexMisread):
            await self.oauth(
                {**self.GOOD, "token_endpoint": "http://index.mcp.paystack.africa/oauth/token"}
            ).endpoints()


class TestTheEnvelope:
    def test_an_event_stream_is_read_message_by_message(self):
        body = (
            'event: message\ndata: {"id": 1, "result": {"a": 1}}\n\ndata: {"id": 2,\ndata:  "result": {}}\n\n'
        )
        assert [m["id"] for m in sse_messages(body)] == [1, 2]

    def test_the_message_that_answers_the_request_is_the_one_taken(self):
        reply = Reply(
            200,
            'data: {"id": 9, "result": {}}\n\ndata: {"id": 3, "result": {"x": 1}}\n\n',
            "text/event-stream",
        )
        assert message_of(reply, 3)["result"] == {"x": 1}

    def test_an_answer_that_is_not_json_is_unreadable(self):
        with pytest.raises(IndexMisread):
            message_of(Reply(200, "<html>", "application/json"), 1)

    def test_a_huge_answer_is_refused(self):
        with pytest.raises(IndexMisread):
            message_of(Reply(200, "x" * 1_000_001, "application/json"), 1)
