# SPDX-License-Identifier: AGPL-3.0-or-later
import json

import pytest

from chat import tickets
from chat.models import Event
from turns import kinds

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def secret(settings):
    settings.WEBHOOK_SECRET = "dummy-hook-secret"


def post(client, body: bytes, signature: str | None = None):
    signature = tickets.sign_webhook(body) if signature is None else signature
    return client.post("/hooks/payment", body, content_type="application/json", HTTP_X_SIGNATURE=signature)


@pytest.fixture
def card(chat):
    Event.objects.create(chat=chat, seq=1, type=kinds.CARD, ref="qt-1", payload={"server": "s"}, created_at=0)
    return chat


def test_the_signature_is_the_one_the_connector_makes():
    """The same vector is asserted by the connector's test (checkout/tests/test_webhook.py)."""
    body = b'{"quote_id":"qt-1"}'
    assert tickets.sign_webhook(body) == (
        "sha256=4ddeb5f2beb31507dd8b828da070ff29ff98d032a72790db3938d5b4bb684946"
    )


def test_a_signed_webhook_refreshes_the_card_of_the_chat_that_holds_the_quote(client, backend, card):
    answer = post(client, json.dumps({"quote_id": "qt-1"}).encode())
    assert answer.status_code == 200 and answer.json() == {"pushed": True}
    assert backend.refreshed == [(card.id, "qt-1")]


def test_a_webhook_for_one_quote_refreshes_that_quote_in_its_own_chat_and_no_other(
    client, backend, card, other_chat
):
    Event.objects.create(
        chat=other_chat, seq=1, type=kinds.CARD, ref="qt-2", payload={"server": "s"}, created_at=0
    )
    post(client, json.dumps({"quote_id": "qt-2"}).encode())
    assert backend.refreshed == [(other_chat.id, "qt-2")]
    post(client, json.dumps({"quote_id": "qt-1"}).encode())
    assert backend.refreshed == [(other_chat.id, "qt-2"), (card.id, "qt-1")]


def test_a_quote_no_chat_holds_pushes_nothing(client, backend, card):
    answer = post(client, json.dumps({"quote_id": "qt-other"}).encode())
    assert answer.json() == {"pushed": False} and backend.refreshed == []


@pytest.mark.parametrize("signature", ["", "sha256=00", "nonsense"])
def test_a_webhook_without_a_valid_signature_is_refused(client, backend, card, signature):
    body = json.dumps({"quote_id": "qt-1"}).encode()
    assert post(client, body, signature).status_code == 401 and backend.refreshed == []


def test_a_signature_made_with_another_secret_is_refused(client, backend, card):
    body = json.dumps({"quote_id": "qt-1"}).encode()
    assert post(client, body, tickets.sign_webhook(body, "other-secret")).status_code == 401


def test_without_a_configured_secret_every_webhook_is_refused(client, backend, card, settings):
    settings.WEBHOOK_SECRET = ""
    body = json.dumps({"quote_id": "qt-1"}).encode()
    assert post(client, body, tickets.sign_webhook(body, "")).status_code == 401


def test_a_body_that_is_not_a_quote_reference_is_a_bad_request(client, backend, card):
    assert post(client, b'{"other": 1}').status_code == 400
    assert post(client, b"not json").status_code == 400
