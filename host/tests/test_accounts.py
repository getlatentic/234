# SPDX-License-Identifier: AGPL-3.0-or-later
"""Sign-in with Google: the endpoints, the session cookie, the owner, the adoption of an anonymous visitor's
chats, sign-out, and what the page offers. Tokens are signed here with generated RSA keys; Google's key
document is a stand-in behind the same cache the views use."""

import json
import re

import pytest
from django.core import signing
from django.test import Client

from accounts import service
from accounts.owner import account_owner
from chat.models import Access, Chat
from turns.ledger_owner import ledger_owner

from .account_support import ACCOUNT_KEY, Device
from .firebase_support import NOW, claims, token

pytestmark = pytest.mark.django_db


def test_the_owner_is_a_stable_32_hex_value_from_the_uid_and_the_key():
    owner = account_owner("uid-abc", ACCOUNT_KEY)
    assert re.fullmatch(r"u:[0-9a-f]{32}", owner)
    assert owner == account_owner("uid-abc", ACCOUNT_KEY)
    assert owner != account_owner("uid-abd", ACCOUNT_KEY)
    assert owner != account_owner("uid-abc", "another-key")
    assert re.fullmatch(r"[0-9a-f]{32}", ledger_owner(owner))
    assert ledger_owner(owner) != ledger_owner("v:" + "0" * 32)


def test_without_firebase_configuration_there_is_no_button_no_accounts_and_the_site_works(client):
    page = client.get("/").content.decode()
    assert "chat-account" not in page and "Continue with Google" not in page
    assert client.post("/auth/session", "{}", content_type="application/json").status_code == 404
    assert client.post("/auth/signout").status_code == 404


def test_with_configuration_the_drawer_offers_google_and_the_chats_button_is_there_for_everyone(sign_in_on):
    page = Device().client.get("/").content.decode()
    assert "Continue with Google" in page and 'data-auth-domain="demo.firebaseapp.com"' in page
    assert 'data-api-key="public-api-key"' in page and "google-g.svg" in page
    chats_button = re.search(r'<button type="button" data-action="chats"[^>]*>', page).group(0)
    assert " hidden" not in chats_button
    assert "Sign out" not in page


def test_a_valid_token_sets_our_session_cookie_and_not_the_token(sign_in_on, key):
    device = Device()
    response = device.sign_in(key)
    assert response.status_code == 200 and response.json() == {"email": "ada@example.com"}
    morsel = device.client.cookies["session"]
    assert morsel["httponly"] and morsel["samesite"] == "Lax" and int(morsel["max-age"]) == 30 * 86400
    assert not morsel["domain"] and morsel["path"] == "/"
    sent = token(key, claims())
    assert all(
        sent.split(".")[1] not in c.value and sent.split(".")[2] not in c.value
        for c in device.client.cookies.values()
    )
    assert set(signing.loads(morsel.value, salt="accounts.session")) == {"o", "e", "n"}


def test_the_cookie_is_secure_outside_development(sign_in_on, key, settings):
    settings.DEBUG = False
    device = Device()
    device.sign_in(key)
    assert device.client.cookies["session"]["secure"]


def test_the_session_value_is_new_at_every_sign_in(sign_in_on, key):
    device = Device()
    device.sign_in(key)
    first = device.client.cookies["session"].value
    device.sign_in(key)
    assert device.client.cookies["session"].value != first


def test_a_garbage_or_wrong_token_is_401_and_sets_no_session(sign_in_on, key):
    device = Device()
    for body in (
        {"idToken": "garbage"},
        {"idToken": ""},
        {},
        {"idToken": 7},
        {"idToken": token(key, claims(aud="x"))},
    ):
        assert device.post("/auth/session", body).status_code == 401
    assert "session" not in device.client.cookies
    bad = Client().post("/auth/session", "not json", content_type="application/json", HTTP_X_CSRFTOKEN="x")
    assert bad.status_code in (401, 403)


def test_the_token_is_refused_without_the_csrf_token(sign_in_on, key):
    client = Client(enforce_csrf_checks=True)
    client.get("/")
    response = client.post(
        "/auth/session", json.dumps({"idToken": token(key, claims())}), content_type="application/json"
    )
    assert response.status_code == 403
    assert client.post("/auth/signout").status_code == 403


def test_a_sign_in_is_rate_limited(sign_in_on, key, backend):
    backend.allow = False
    response = Device().sign_in(key)
    assert response.status_code == 429
    assert backend.rate_keys and backend.rate_keys[-1].startswith("auth:")


def test_the_emulator_is_not_accepted_when_it_is_not_configured(sign_in_on, settings):
    unsigned = token(None, claims(), header={"alg": "none", "typ": "JWT"}, signature="")
    device = Device()
    assert device.post("/auth/session", {"idToken": unsigned}).status_code == 401
    assert "session" not in device.client.cookies
    settings.FIREBASE_AUTH_EMULATOR_HOST = "127.0.0.1:9099"
    assert device.post("/auth/session", {"idToken": unsigned}).status_code == 200


def test_keys_that_cannot_be_fetched_are_503_not_a_sign_in(sign_in_on, key):
    from accounts.keys import GoogleKeys, KeysUnavailable

    def down(url):
        raise KeysUnavailable("down")

    service.set_keys(GoogleKeys(down))
    assert Device().sign_in(key).status_code == 503


def test_a_tampered_or_expired_session_cookie_is_an_anonymous_visitor(sign_in_on, key, monkeypatch):
    device = Device()
    device.sign_in(key)
    value = device.client.cookies["session"].value
    device.client.cookies["session"] = value[:-2] + ("AA" if not value.endswith("AA") else "BB")
    assert "Sign out" not in device.client.get("/").content.decode()
    device.client.cookies["session"] = value
    assert "Sign out" in device.client.get("/").content.decode()
    monkeypatch.setattr("django.core.signing.time.time", lambda: NOW + 31 * 86400 + 10**9)
    assert "Sign out" not in device.client.get("/").content.decode()


def test_a_signed_in_drawer_shows_the_email_an_initial_and_sign_out(sign_in_on, key):
    device = Device()
    device.sign_in(key)
    page = device.client.get("/").content.decode()
    assert "ada@example.com" in page and "Sign out" in page and "Continue with Google" not in page
    assert re.search(r">A</span>", page)


def test_the_anonymous_visitors_chats_become_the_accounts_at_sign_in(sign_in_on, key):
    device = Device()
    first, second = device.chat(), device.chat()
    anonymous = Chat.objects.get(pk=first).owner
    assert anonymous.startswith("v:")
    device.sign_in(key)
    owner = account_owner("uid-abc", ACCOUNT_KEY)
    assert set(Chat.objects.filter(owner=owner).values_list("id", flat=True)) == {first, second}
    assert not Chat.objects.filter(owner=anonymous).exists()
    page = device.client.get("/").content.decode()
    assert first in page and second in page
    assert device.client.get(f"/c/{first}/").status_code == 200
    assert "visitor" not in device.client.cookies or not device.client.cookies["visitor"].value


def test_a_second_device_with_the_same_uid_has_the_same_chats_and_the_same_owner(sign_in_on, key):
    one, two = Device(), Device()
    mine = one.chat()
    one.sign_in(key)
    its_own = two.chat()
    two.sign_in(key)
    owner = account_owner("uid-abc", ACCOUNT_KEY)
    assert Chat.objects.get(pk=mine).owner == Chat.objects.get(pk=its_own).owner == owner
    page = two.client.get("/").content.decode()
    assert mine in page and its_own in page
    assert one.client.get(f"/c/{its_own}/").status_code == 200
    assert two.client.get("/").wsgi_request.owner == one.client.get("/").wsgi_request.owner == owner


def test_another_account_sees_none_of_it(sign_in_on, key):
    one, other = Device(), Device()
    chat = one.chat()
    one.sign_in(key)
    other.sign_in(key, uid="uid-other", email="grace@example.com")
    assert other.client.get(f"/c/{chat}/").status_code == 404
    assert chat not in other.client.get("/").content.decode()


def test_signing_in_twice_changes_nothing_and_loses_nothing(sign_in_on, key):
    device = Device()
    chat = device.chat()
    device.sign_in(key)
    device.sign_in(key)
    assert Chat.objects.get(pk=chat).owner == account_owner("uid-abc", ACCOUNT_KEY)
    assert Chat.objects.count() == 1


def test_guest_passes_move_to_the_account_without_a_duplicate(sign_in_on, key):
    owner_device, guest = Device(), Device()
    shared = owner_device.chat()
    link = owner_device.post(f"/c/{shared}/share").json()["url"].removeprefix("http://testserver")
    guest.client.get(link)
    guest_owner = guest.client.get("/").wsgi_request.owner
    assert Access.objects.filter(visitor=guest_owner).count() == 1
    guest.sign_in(key, uid="uid-guest", email="guest@example.com")
    account = account_owner("uid-guest", ACCOUNT_KEY)
    assert list(Access.objects.values_list("visitor", flat=True)) == [account]
    assert guest.client.get(f"/c/{shared}/").status_code == 200


def test_a_pass_the_account_already_holds_is_not_duplicated_and_a_pass_to_its_own_chat_is_dropped(
    sign_in_on, key
):
    owner_device, anonymous, signed_in = Device(), Device(), Device()
    shared = owner_device.chat()
    link = owner_device.post(f"/c/{shared}/share").json()["url"].removeprefix("http://testserver")
    anonymous.client.get(link)
    visitor = anonymous.client.get("/").wsgi_request.owner
    signed_in.sign_in(key, uid="uid-guest", email="guest@example.com")
    signed_in.client.get(link)
    account = account_owner("uid-guest", ACCOUNT_KEY)
    assert set(Access.objects.values_list("visitor", flat=True)) == {visitor, account}
    anonymous.sign_in(key, uid="uid-guest", email="guest@example.com")
    assert list(Access.objects.filter(chat_id=shared).values_list("visitor", flat=True)) == [account]

    mine = Device()
    own = mine.chat()
    mine.sign_in(key, uid="uid-own", email="own@example.com")
    own_link = mine.post(f"/c/{own}/share").json()["url"].removeprefix("http://testserver")
    elsewhere = Device()
    elsewhere.client.get(own_link)
    assert Access.objects.filter(chat_id=own).exists()
    elsewhere.sign_in(key, uid="uid-own", email="own@example.com")
    assert not Access.objects.filter(chat_id=own).exists()


def test_a_person_already_signed_in_adopts_no_visitors_chats_by_signing_in_as_someone_else(sign_in_on, key):
    stranger, device = Device(), Device()
    theirs = stranger.chat()
    device.sign_in(key)
    device.client.cookies["visitor"] = stranger.client.cookies["visitor"].value
    assert device.sign_in(key, uid="uid-other", email="grace@example.com").status_code == 200
    assert Chat.objects.get(pk=theirs).owner.startswith("v:")


def test_a_session_cookie_is_no_account_where_sign_in_is_off(sign_in_on, key, settings):
    device = Device()
    device.sign_in(key)
    assert device.client.get("/").wsgi_request.owner == account_owner("uid-abc", ACCOUNT_KEY)
    settings.SIGN_IN_ENABLED = False
    assert device.client.get("/").wsgi_request.owner.startswith("v:")


def test_sign_out_ends_as_a_fresh_visitor_who_cannot_see_the_accounts_chats(sign_in_on, key):
    device = Device()
    chat = device.chat()
    device.sign_in(key)
    assert device.post("/auth/signout").status_code == 204
    assert not device.client.cookies["session"].value
    page = device.client.get("/")
    assert page.wsgi_request.owner.startswith("v:") and page.wsgi_request.owner != account_owner(
        "uid-abc", ACCOUNT_KEY
    )
    assert chat not in page.content.decode() and device.client.get(f"/c/{chat}/").status_code == 404
    assert "Continue with Google" in page.content.decode()
    signing_back = device.sign_in(key)
    assert signing_back.status_code == 200 and chat in device.client.get("/").content.decode()


def test_signing_out_twice_or_when_anonymous_keeps_the_visitor(sign_in_on):
    device = Device()
    chat = device.chat()
    cookie = device.client.cookies["visitor"].value
    assert device.post("/auth/signout").status_code == 204
    assert device.client.cookies["visitor"].value == cookie
    assert device.client.get(f"/c/{chat}/").status_code == 200


def test_the_page_policy_adds_only_the_narrow_sign_in_origins(sign_in_on, settings):
    settings.SANDBOX_ORIGIN = "https://sandbox.example.com"
    policy = Device().client.get("/")["Content-Security-Policy"]
    directives = dict(part.split(" ", 1) for part in policy.split("; "))
    assert directives["script-src"] == "'self' https://apis.google.com"
    assert directives["frame-src"] == "https://sandbox.example.com https://demo.firebaseapp.com"
    assert directives["connect-src"].split() == [
        "'self'",
        "https://identitytoolkit.googleapis.com",
        "https://securetoken.googleapis.com",
        "https://apis.google.com",
        "https://www.google.com/images/cleardot.gif",
    ]
    assert directives["style-src"] == "'self'" and directives["img-src"] == "'self' data:"
    assert directives["frame-ancestors"] == "'none'" and directives["default-src"] == "'self'"


def test_the_policy_is_unchanged_without_sign_in(client, settings):
    settings.SANDBOX_ORIGIN = "https://sandbox.example.com"
    assert client.get("/")["Content-Security-Policy"] == (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; "
        "frame-src https://sandbox.example.com; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    )


def test_the_emulator_origin_is_allowed_only_when_the_emulator_is_configured(sign_in_on, settings):
    assert "127.0.0.1:9099" not in Device().client.get("/")["Content-Security-Policy"]
    settings.FIREBASE_AUTH_EMULATOR_HOST = "127.0.0.1:9099"
    assert "http://127.0.0.1:9099" in Device().client.get("/")["Content-Security-Policy"]
