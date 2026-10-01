# SPDX-License-Identifier: AGPL-3.0-or-later
import json

import pytest

from chat.models import Chat, Event
from turns import kinds

pytestmark = pytest.mark.django_db


def test_a_message_goes_to_the_chats_object_and_the_first_one_names_the_chat(visitor, backend):
    chat_id = visitor.new_chat()
    answer = visitor.post(f"/c/{chat_id}/send", json={"text": "  Pay ₦2,500 to Demo Kitchen  "})
    assert answer.status_code == 200 and answer.json() == {"seq": 1, "task": "t1"}
    assert backend.submitted == [(chat_id, kinds.USER, "Pay ₦2,500 to Demo Kitchen", None)]
    assert Chat.objects.get(pk=chat_id).title == "Pay ₦2,500 to Demo Kitchen"
    visitor.post(f"/c/{chat_id}/send", json={"text": "second"})
    assert Chat.objects.get(pk=chat_id).title == "Pay ₦2,500 to Demo Kitchen"


@pytest.mark.parametrize(
    ("text", "code"),
    [("", "empty"), ("x" * 501, "too_long"), ("card 4242 4242 4242 4242", "card_data"), (None, "empty")],
)
def test_a_message_that_is_empty_too_long_or_holds_a_card_number_never_reaches_the_object(
    visitor, backend, text, code
):
    chat_id = visitor.new_chat()
    answer = visitor.post(f"/c/{chat_id}/send", json={"text": text})
    assert answer.status_code == 422 and answer.json()["error"] == code
    assert backend.submitted == []


def test_a_visitor_over_the_rate_limit_is_told_to_wait(visitor, backend):
    chat_id = visitor.new_chat()
    backend.allow = False
    answer = visitor.post(f"/c/{chat_id}/send", json={"text": "hi"})
    assert answer.status_code == 429 and backend.submitted == []


def test_the_object_refusing_an_input_is_passed_on(visitor, backend):
    chat_id = visitor.new_chat()
    backend.answer = {"error": "card_data", "message": "no"}
    assert visitor.post(f"/c/{chat_id}/send", json={"text": "hi"}).status_code == 422


def test_a_card_message_and_a_card_note_are_recorded_as_the_cards_own(visitor, backend):
    chat_id = visitor.new_chat()
    visitor.post(f"/c/{chat_id}/message", json={"text": "hello"})
    visitor.post(f"/c/{chat_id}/context", json={"text": "The card now shows: paid."})
    assert [call[1] for call in backend.submitted] == [kinds.CARD_MESSAGE, kinds.CARD_CONTEXT]
    assert Chat.objects.get(pk=chat_id).title == ""


def test_nothing_can_be_sent_to_a_chat_that_is_not_mine(visitor, backend):
    from django.test import Client

    chat_id = visitor.new_chat()
    stranger = Client()
    token = stranger.get("/api/me").json()["csrf"]
    posted = stranger.post(
        f"/c/{chat_id}/send",
        json.dumps({"text": "hi"}),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=token,
    )
    assert posted.status_code == 404 and backend.submitted == []


def test_a_post_without_the_csrf_token_is_refused(visitor):
    from django.test import Client

    chat_id = visitor.new_chat()
    strict = Client(enforce_csrf_checks=True)
    strict.cookies = visitor.client.cookies
    assert strict.post(f"/c/{chat_id}/send", "{}", content_type="application/json").status_code == 403


def test_a_cards_tool_call_is_relayed_and_a_refusal_is_a_403(visitor, backend):
    chat_id = visitor.new_chat()
    ok = visitor.post(
        f"/c/{chat_id}/call", json={"server": "s", "name": "approve_quote", "arguments": {"quote_id": "q"}}
    )
    assert ok.status_code == 200 and ok.json()["content"][0]["text"] == "ok"
    assert backend.submitted[-1] == (chat_id, "card_call", "s", "approve_quote", {"quote_id": "q"})
    backend.card_answer = {"error": "no card"}
    refused = visitor.post(f"/c/{chat_id}/call", json={"server": "s", "name": "x", "arguments": {}})
    assert refused.status_code == 403 and refused.json() == {"error": "no card"}


def test_the_page_is_the_stored_history_and_says_where_the_stream_starts(visitor):
    chat_id = visitor.new_chat()
    chat = Chat.objects.get(pk=chat_id)
    rows = [
        (kinds.USER, {"text": "pay"}, None),
        (kinds.TEXT, {"message": "m1", "text": "Che"}, None),
        (kinds.ASSISTANT, {"message": "m1", "text": "Checking", "finish_reason": "stop", "upto": 1}, None),
        (kinds.TEXT, {"message": "m2", "text": "half a rep"}, None),
    ]
    for seq, (type, payload, ref) in enumerate(rows, 1):
        Event.objects.create(chat=chat, seq=seq, type=type, payload=payload, ref=ref or "", created_at=0)
    page = visitor.client.get(f"/c/{chat_id}/").content.decode()
    assert 'data-last-seq="4"' in page
    assert page.count('data-message="m1"') == 1 and "Checking" in page and "half a rep" in page
    assert "Che<" not in page


def test_a_working_chat_is_marked_working_and_a_quiet_one_is_not(visitor):
    chat_id = visitor.new_chat()
    chat = Chat.objects.get(pk=chat_id)
    Event.objects.create(chat=chat, seq=1, type=kinds.TURN_STARTED, payload={"task": "t"}, created_at=0)
    assert "data-working" in visitor.client.get(f"/c/{chat_id}/").content.decode().split("data-send-url")[0]
    Event.objects.create(chat=chat, seq=2, type=kinds.TURN_FINISHED, payload={"task": "t"}, created_at=0)
    assert (
        "data-working" not in visitor.client.get(f"/c/{chat_id}/").content.decode().split("data-send-url")[0]
    )


def test_the_page_forbids_other_peoples_scripts_and_being_framed(visitor):
    chat_id = visitor.new_chat()
    response = visitor.client.get(f"/c/{chat_id}/")
    policy = response["Content-Security-Policy"]
    assert "script-src 'self'" in policy and "frame-ancestors 'none'" in policy
    assert "frame-src 'none'" in policy
    assert response["X-Frame-Options"] == "DENY"


def test_the_socket_address_is_not_a_page(visitor):
    chat_id = visitor.new_chat()
    assert visitor.client.get(f"/c/{chat_id}/ws").status_code == 426


def test_a_card_page_with_a_head_gets_the_colour_scheme_declared_inside_it():
    from chat.views.cards import with_color_scheme

    assert with_color_scheme("<html><HEAD lang=x><title>t</title></head>") == (
        '<html><HEAD lang=x><meta name="color-scheme" content="light dark"><title>t</title></head>'
    )


def test_a_cards_notes_have_a_limit_of_their_own_and_a_repeating_card_is_stopped(visitor, backend):
    chat_id = visitor.new_chat()
    assert visitor.post(f"/c/{chat_id}/context", json={"text": "Card shows: waiting"}).status_code == 200
    assert backend.rate_keys[-1].startswith("note:")
    delivered = len(backend.submitted)
    backend.allow = False
    stopped = visitor.post(f"/c/{chat_id}/context", json={"text": "Card shows: waiting again"})
    assert stopped.status_code == 429 and len(backend.submitted) == delivered
