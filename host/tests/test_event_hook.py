# SPDX-License-Identifier: AGPL-3.0-or-later
"""How a quote's ending reaches this host: the connector's signed MCP event at /hooks/events, the
verification it sends first, and the chat that holds the quote's card, which shows the ending and tells the
model."""

import base64
import hashlib
import hmac
import json
import time

import pytest

from chat.models import Event
from turns import kinds, quote_events

pytestmark = pytest.mark.django_db
SECRET = "dummy-events-secret"


@pytest.fixture(autouse=True)
def secret(settings):
    settings.EVENTS_SECRET = SECRET


def signed(body: bytes, message_id="evt_1", at=None, secret=SECRET) -> dict[str, str]:
    stamp = str(int(time.time() if at is None else at))
    key = base64.b64decode(quote_events.secret_of(secret).removeprefix("whsec_"))
    mac = base64.b64encode(hmac.new(key, f"{message_id}.{stamp}.".encode() + body, hashlib.sha256).digest())
    return {
        "HTTP_WEBHOOK_ID": message_id,
        "HTTP_WEBHOOK_TIMESTAMP": stamp,
        "HTTP_WEBHOOK_SIGNATURE": f"v1,{mac.decode()}",
    }


def post(client, payload: dict, **headers):
    body = json.dumps(payload).encode()
    return client.post("/hooks/events", body, content_type="application/json", **(headers or signed(body)))


def ended(quote_id="qt-1", state="settled", event_id="evt_qt-1_settled"):
    data = {
        "quote_id": quote_id,
        "connector": "airtime",
        "state": state,
        "amount_kobo": 50000,
        "description": "MTN",
    }
    return {"eventId": event_id, "name": "quote.finished", "timestamp": "2026-10-06T10:00:00Z", "data": data}


@pytest.fixture
def card(chat):
    Event.objects.create(
        chat=chat, seq=1, type=kinds.CARD, ref="qt-1", payload={"server": "airtime"}, created_at=0
    )
    return chat


def test_the_verification_is_answered_with_its_challenge(client):
    assert post(client, {"type": "verification", "challenge": "c-123"}).json() == {"challenge": "c-123"}


def test_an_ending_reaches_the_chat_that_holds_the_quote_and_the_model_is_told(client, backend, card):
    answer = post(client, ended())
    assert answer.status_code == 200 and answer.json() == {"told": True}
    (chat_id, quote_id, event_id, text) = backend.ended[-1]
    assert (chat_id, quote_id, event_id) == (card.id, "qt-1", "evt_qt-1_settled")
    assert text == "Quote qt-1 (₦500, MTN) paid and done."


def test_an_ending_no_chat_holds_ends_the_subscription(client, backend, card):
    assert post(client, ended("qt-gone")).status_code == 410 and backend.ended == []


def test_another_event_is_acknowledged_and_ignored(client, backend, card):
    assert post(client, {"eventId": "e", "name": "quote.created", "data": {}}).status_code == 204


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"HTTP_WEBHOOK_ID": "evt_1", "HTTP_WEBHOOK_TIMESTAMP": "1", "HTTP_WEBHOOK_SIGNATURE": "v1,AAAA"},
    ],
)
def test_an_unsigned_or_wrongly_signed_event_is_refused(client, backend, card, headers):
    body = json.dumps(ended()).encode()
    answer = client.post("/hooks/events", body, content_type="application/json", **headers)
    assert answer.status_code == 401 and backend.ended == []


def test_a_signature_by_another_key_an_old_timestamp_or_another_id_is_refused(client, backend, card):
    body = json.dumps(ended()).encode()
    for headers in (
        signed(body, secret="other"),
        signed(body, at=time.time() - 600),
        {**signed(body), "HTTP_WEBHOOK_ID": "evt_2"},
    ):
        assert (
            client.post("/hooks/events", body, content_type="application/json", **headers).status_code == 401
        )
    assert backend.ended == []


def test_one_of_several_signatures_is_enough_as_during_a_key_rotation(client, backend, card):
    body = json.dumps(ended()).encode()
    headers = signed(body)
    headers["HTTP_WEBHOOK_SIGNATURE"] = "v1,AAAA " + headers["HTTP_WEBHOOK_SIGNATURE"]
    assert client.post("/hooks/events", body, content_type="application/json", **headers).status_code == 200


def test_without_a_secret_there_is_no_endpoint(client, settings):
    settings.EVENTS_SECRET = ""
    assert post(client, {"type": "verification", "challenge": "c"}).status_code == 404


def test_the_subscription_asks_for_one_quote_with_the_hosts_callback_and_key():
    found = quote_events.subscription("qt-9", "https://234.example/", SECRET)
    assert found["arguments"] == {"quote_id": "qt-9"} and found["name"] == "quote.finished"
    assert found["delivery"]["url"] == "https://234.example/hooks/events"
    assert (
        found["delivery"]["secret"].startswith("whsec_")
        and len(base64.b64decode(found["delivery"]["secret"][6:])) == 32
    )
