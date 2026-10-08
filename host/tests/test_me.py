# SPDX-License-Identifier: AGPL-3.0-or-later
import json

import pytest
from django.test import Client

from .account_support import Device
from .firebase_support import PROJECT

pytestmark = pytest.mark.django_db

CONTRACT = {"product", "csrf", "account", "signIn", "botCheck", "memory", "chats", "problem"}


def test_the_answer_is_exactly_what_the_static_home_cannot_hold(client):
    answer = client.get("/api/me")
    me = answer.json()
    assert answer.status_code == 200 and set(me) == CONTRACT
    assert me["product"] == "234" and me["csrf"] and me["account"] is None
    assert me["signIn"] is None and me["botCheck"] is None and me["memory"] is False and me["chats"] == []


def test_it_is_never_stored_and_never_read_by_another_site(client):
    answer = client.get("/api/me")
    assert answer["Cache-Control"] == "no-store, private"
    assert answer["Cross-Origin-Resource-Policy"] == "same-origin"
    assert "Access-Control-Allow-Origin" not in answer


@pytest.mark.parametrize(
    ("site", "status"), [("same-origin", 200), ("none", 200), ("cross-site", 403), ("same-site", 403)]
)
def test_a_browser_that_says_the_request_is_from_another_site_is_refused(client, site, status):
    assert client.get("/api/me", HTTP_SEC_FETCH_SITE=site).status_code == status


def test_it_only_answers_get(client):
    assert client.post("/api/me").status_code == 405


def test_the_first_answer_makes_the_visitor_and_the_csrf_cookies_and_the_next_keeps_them():
    client = Client()
    first = client.get("/api/me")
    assert {"visitor", "csrftoken"} <= set(first.cookies)
    kept = {name: morsel.value for name, morsel in client.cookies.items()}
    second = client.get("/api/me")
    assert not second.cookies.get("visitor") and {name: m.value for name, m in client.cookies.items()} == kept
    assert all(morsel["domain"] == "" for morsel in client.cookies.values())


def test_the_token_it_gives_is_the_one_a_post_needs(visitor, backend):
    chat = "a" * 32
    strict = Client(enforce_csrf_checks=True)
    token = strict.get("/api/me").json()["csrf"]
    body = json.dumps({"text": "hi"})
    assert strict.post(f"/c/{chat}/start", body, content_type="application/json").status_code == 403
    sent = strict.post(f"/c/{chat}/start", body, content_type="application/json", HTTP_X_CSRFTOKEN=token)
    assert sent.status_code == 200


def test_it_lists_the_visitors_chats_with_their_addresses_and_whose_they_are(visitor):
    first, second = visitor.new_chat(), visitor.new_chat()
    assert visitor.client.get("/api/me").json()["chats"] == [
        {"id": second, "title": "", "url": f"/c/{second}/", "deleteUrl": f"/c/{second}/delete", "mine": True},
        {"id": first, "title": "", "url": f"/c/{first}/", "deleteUrl": f"/c/{first}/delete", "mine": True},
    ]


def test_it_names_who_is_signed_in_and_the_public_firebase_identifiers(sign_in_on, key):
    device = Device()
    assert device.me()["account"] is None
    device.sign_in(key)
    me = device.me()
    assert me["account"] == {"email": "ada@example.com", "initial": "A"} and me["memory"] is True
    assert me["signIn"] == {
        "apiKey": "public-api-key",
        "authDomain": "demo.firebaseapp.com",
        "projectId": PROJECT,
        "emulator": "",
    }


def test_it_names_the_emulator_only_where_one_is_configured(sign_in_on, settings):
    settings.FIREBASE_AUTH_EMULATOR_HOST = "127.0.0.1:9099"
    assert Device().me()["signIn"]["emulator"] == "http://127.0.0.1:9099"
