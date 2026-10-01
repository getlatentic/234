# SPDX-License-Identifier: AGPL-3.0-or-later
import re
import secrets
import struct
from pathlib import Path

import pytest
from django.test import Client

from chat.models import Chat
from chat.shell import PLACEHOLDER_CHAT
from turns import kinds

pytestmark = pytest.mark.django_db

BRAND = Path(__file__).resolve().parents[1] / "src" / "chat" / "static" / "chat" / "brand"


def draft_of(visitor) -> str:
    """An id of the kind the page mints in the browser: 32 random hex characters."""
    return secrets.token_hex(16)


def test_the_home_page_is_a_composer_for_a_chat_that_is_not_stored(visitor):
    page = visitor.client.get("/")
    html = page.content.decode()
    assert page.status_code == 200 and "data-draft" in html
    assert re.search(r"<textarea[^>]*autofocus", html)
    assert f"/c/{PLACEHOLDER_CHAT}/start" in html
    assert Chat.objects.count() == 0


def test_a_visitor_with_earlier_chats_still_gets_a_fresh_composer_and_the_page_lists_the_chats(visitor):
    earlier = visitor.new_chat()
    html = visitor.client.get("/").content.decode()
    assert "data-draft" in html and earlier not in html
    assert [chat["id"] for chat in visitor.client.get("/api/me").json()["chats"]] == [earlier]


def test_the_home_page_is_the_same_for_every_visitor(visitor, client):
    visitor.new_chat()
    assert client.get("/").content == Client().get("/").content


def test_the_first_message_makes_the_chat_and_names_it(visitor, backend):
    chat_id = draft_of(visitor)
    answer = visitor.post(f"/c/{chat_id}/start", json={"text": "  Pay ₦2,500 to Demo Kitchen  "})
    assert answer.status_code == 200
    assert backend.submitted == [(chat_id, kinds.USER, "Pay ₦2,500 to Demo Kitchen", None)]
    chat = Chat.objects.get()
    assert chat.id == chat_id and chat.title == "Pay ₦2,500 to Demo Kitchen" and chat.owner.startswith("v:")
    assert visitor.client.get(f"/c/{chat_id}/").status_code == 200


def test_a_second_message_to_the_same_id_joins_the_chat_and_makes_no_other(visitor, backend):
    chat_id = draft_of(visitor)
    visitor.post(f"/c/{chat_id}/start", json={"text": "one"})
    visitor.post(f"/c/{chat_id}/start", json={"text": "two"})
    assert Chat.objects.count() == 1 and [call[2] for call in backend.submitted] == ["one", "two"]
    assert Chat.objects.get().title == "one"


@pytest.mark.parametrize(
    ("text", "code"), [("", "empty"), ("x" * 501, "too_long"), ("card 4242 4242 4242 4242", "card_data")]
)
def test_a_refused_first_message_leaves_no_chat(visitor, backend, text, code):
    answer = visitor.post(f"/c/{draft_of(visitor)}/start", json={"text": text})
    assert answer.status_code == 422 and answer.json()["error"] == code
    assert Chat.objects.count() == 0 and backend.submitted == []


def test_a_first_message_over_the_rate_limit_leaves_no_chat(visitor, backend):
    backend.allow = False
    assert visitor.post(f"/c/{draft_of(visitor)}/start", json={"text": "hi"}).status_code == 429
    assert Chat.objects.count() == 0


def test_a_first_message_the_object_refuses_leaves_no_chat(visitor, backend):
    backend.answer = {"error": "card_data", "message": "no"}
    assert visitor.post(f"/c/{draft_of(visitor)}/start", json={"text": "hi"}).status_code == 422
    assert Chat.objects.count() == 0


def test_a_first_message_that_fails_in_the_object_leaves_no_chat(visitor, backend):
    def broken(*args):
        raise RuntimeError("object unreachable")

    backend.submit = broken
    chat_id = draft_of(visitor)
    with pytest.raises(RuntimeError):
        visitor.post(f"/c/{chat_id}/start", json={"text": "hi"})
    assert Chat.objects.count() == 0


def test_an_id_that_is_someone_elses_chat_cannot_be_started_again(visitor, backend):
    taken = Chat.objects.create(owner="v:someone-else")
    assert visitor.post(f"/c/{taken.id}/start", json={"text": "hi"}).status_code == 404
    assert backend.submitted == [] and Chat.objects.get().owner == "v:someone-else"


def test_a_stranger_cannot_reach_a_chat_by_starting_it(visitor, backend):
    chat_id = visitor.new_chat()
    stranger = Client()
    token = stranger.get("/api/me").json()["csrf"]
    posted = stranger.post(
        f"/c/{chat_id}/start", '{"text": "hi"}', content_type="application/json", HTTP_X_CSRFTOKEN=token
    )
    assert posted.status_code == 404 and backend.submitted == []


def test_the_chats_are_a_sheet_on_the_page_and_a_new_chat_is_a_link_to_the_composer(visitor):
    mine = visitor.new_chat()
    html = visitor.client.get(f"/c/{mine}/").content.decode()
    assert "<dialog" in html and f'href="/c/{mine}/" aria-current="page"' in html
    assert 'href="/"' in html and visitor.client.get("/chats").status_code == 404


def test_the_page_has_no_header_and_names_the_product_only_where_it_is_set(visitor):
    html = visitor.client.get("/").content.decode()
    assert "<header" not in html and "<footer" not in html and "<nav" not in html
    assert "<title>234</title>" in html and 'name="application-name" content="234"' in html
    assert 'name="description" content="Talk and do anything with 234."' in html
    assert (
        'property="og:title" content="234"' in html
        and 'property="og:description" content="Talk and do anything with 234."' in html
    )
    body = html.split("<body", 1)[1]
    assert (
        'data-slot="wordmark" role="img" aria-label="234"' in body
        and "<svg" in body.split('data-slot="wordmark"')[1].split("</p>")[0]
    )
    assert 'placeholder="Ask 234"' in body and '<label class="sr-only" for="text">Ask 234</label>' in body
    assert "Simulated" not in body and "Connectors unreachable" not in body


def test_the_composer_asks_with_the_product_name_from_the_one_setting_even_a_long_one(visitor, settings):
    settings.PRODUCT_NAME = "Northwind Agent Checkout Demos"
    body = visitor.client.get("/").content.decode().split("<body", 1)[1]
    assert 'placeholder="Ask Northwind Agent Checkout Demos"' in body
    assert ">Ask Northwind Agent Checkout Demos</label>" in body and "Ask 234" not in body
    assert 'aria-label="Northwind Agent Checkout Demos"' in body


def test_the_composer_is_a_pill_with_named_controls_and_room_for_a_keyboard_and_a_notch(visitor):
    mine = visitor.new_chat()
    for html in (
        visitor.client.get("/").content.decode(),
        visitor.client.get(f"/c/{mine}/").content.decode(),
    ):
        assert 'aria-label="Chats"' in html and 'aria-label="Send"' in html and 'enterkeyhint="send"' in html
        assert "interactive-widget=resizes-content" in html and "viewport-fit=cover" in html
        assert "env(safe-area-inset-bottom)" in html and "min-h-dvh" in html and "--keyboard-inset" in html
        assert "size-11" in html and re.search(r'data-cancel-url="/c/[0-9a-f]{32}/cancel"', html)
        assert 'data-slot="working"' not in html


def test_a_chat_is_titled_by_its_first_message(visitor):
    mine = visitor.new_chat()
    Chat.objects.filter(pk=mine).update(title="Pay for lunch")
    assert "<title>Pay for lunch</title>" in visitor.client.get(f"/c/{mine}/").content.decode()


def test_the_manifest_carries_the_product_name_from_the_one_setting(client, settings):
    settings.PRODUCT_NAME = "renamed"
    answer = client.get("/manifest.webmanifest")
    assert answer["Content-Type"] == "application/manifest+json"
    assert answer.json()["name"] == "renamed" and answer.json()["short_name"] == "renamed"
    assert answer.json()["description"] == "Talk and do anything with renamed."
    assert "renamed" in client.get("/").content.decode()
    assert "visitor" not in answer.cookies


def test_the_manifest_names_the_icons_and_they_are_the_sizes_it_says(client):
    icons = client.get("/manifest.webmanifest").json()["icons"]
    assert [(i["sizes"], i["purpose"]) for i in icons] == [
        ("192x192", "any"),
        ("512x512", "any"),
        ("512x512", "maskable"),
    ]
    for icon in icons:
        path = BRAND / icon["src"].rsplit("/", 1)[1]
        width, height = struct.unpack(">II", path.read_bytes()[16:24])
        assert icon["type"] == "image/png" and f"{width}x{height}" == icon["sizes"]
    assert icons[0]["src"].startswith("/static/chat/brand/")


def test_the_page_links_the_favicon_and_the_touch_icon_and_they_exist(client):
    html = client.get("/").content.decode()
    for link in ("favicon.svg", "favicon.ico", "apple-touch-icon.png"):
        assert f'href="/static/chat/brand/{link}"' in html and (BRAND / link).stat().st_size > 0
    assert struct.unpack(">II", (BRAND / "apple-touch-icon.png").read_bytes()[16:24]) == (180, 180)


def test_a_caller_that_loses_the_race_for_an_id_gets_the_winners_chat(visitor, backend, monkeypatch):
    """D1 raises its own exception for the loser's insert, after the winner's row is there."""
    chat_id = draft_of(visitor)
    real_create = Chat.objects.create

    def lose(**fields):
        real_create(**fields)
        raise RuntimeError("D1_ERROR: UNIQUE constraint failed: chat_chat.id")

    monkeypatch.setattr(Chat.objects, "create", lose)
    assert visitor.post(f"/c/{chat_id}/start", json={"text": "hi"}).status_code == 200
    assert Chat.objects.count() == 1 and len(backend.submitted) == 1


def test_a_failure_that_left_no_chat_is_not_swallowed(visitor, monkeypatch):
    def broken(**fields):
        raise RuntimeError("database unreachable")

    monkeypatch.setattr(Chat.objects, "create", broken)
    with pytest.raises(RuntimeError):
        visitor.post(f"/c/{draft_of(visitor)}/start", json={"text": "hi"})
