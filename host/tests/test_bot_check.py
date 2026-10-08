# SPDX-License-Identifier: AGPL-3.0-or-later
"""Turnstile before a visitor's first message (chat/bot_check.py): the message that would make a chat is
checked, and only it; a person who is signed in, and a second message to a chat that exists, are not;
Cloudflare being down lets the message through to the limits that were always there; and the page may reach
Cloudflare only where Turnstile is on."""

import json
import secrets
from urllib.parse import parse_qs

import httpx
import pytest

from chat import bot_check
from chat.models import Chat
from chat.security import page_policy

pytestmark = pytest.mark.django_db
KEY, SECRET = "0x4AAAtest-site-key", "0x4AAAtest-secret"
GOOD = {"success": True, "action": "start", "hostname": "testserver"}


class Cloudflare:
    """siteverify, played: what it was asked and what it answers."""

    def __init__(self) -> None:
        self.asked: list[dict[str, str]] = []
        self.answer: tuple[int, bytes] | Exception = (200, json.dumps(GOOD).encode())

    def __call__(self, form: str) -> tuple[int, bytes]:
        self.asked.append({k: v[0] for k, v in parse_qs(form).items()})
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer

    def says(self, body: dict | bytes, status: int = 200) -> None:
        self.answer = (status, body if isinstance(body, bytes) else json.dumps(body).encode())


@pytest.fixture
def cloudflare(settings, monkeypatch):
    settings.TURNSTILE_SITE_KEY, settings.TURNSTILE_SECRET, settings.TURNSTILE_ENABLED = KEY, SECRET, True
    settings.TURNSTILE_HOSTNAMES, settings.ALLOWED_HOSTS = [], ["testserver"]
    played = Cloudflare()
    monkeypatch.setattr(bot_check, "ask", played)
    return played


def first_message(visitor, token: object = "a-token", chat_id: str | None = None, **headers):
    body = {"text": "hello"} if token is None else {"text": "hello", "botToken": token}
    return visitor.post(f"/c/{chat_id or secrets.token_hex(16)}/start", json=body, **headers)


def test_without_turnstile_a_first_message_needs_no_token(visitor, backend):
    assert first_message(visitor, None).status_code == 200


def test_a_first_message_with_a_good_token_makes_the_chat_and_cloudflare_was_asked_with_the_secret(
    visitor, backend, cloudflare
):
    assert first_message(visitor, "tok-1", HTTP_CF_CONNECTING_IP="203.0.113.7").status_code == 200
    assert cloudflare.asked == [{"secret": SECRET, "response": "tok-1", "remoteip": "203.0.113.7"}]
    assert Chat.objects.count() == 1


@pytest.mark.parametrize("token", [None, "", 42, "x" * 3000])
def test_a_first_message_with_no_usable_token_is_refused_without_asking_cloudflare(
    visitor, cloudflare, token
):
    answer = first_message(visitor, token)
    assert answer.status_code == 403 and answer.json()["error"] == "bot_check"
    assert "challenges.cloudflare.com" in answer.json()["message"]
    assert cloudflare.asked == [] and Chat.objects.count() == 0


def test_a_token_cloudflare_refuses_leaves_no_chat_and_no_message(visitor, backend, cloudflare):
    cloudflare.says({"success": False, "error-codes": ["invalid-input-response"]})
    assert first_message(visitor).status_code == 403
    assert Chat.objects.count() == 0 and backend.submitted == []


@pytest.mark.parametrize(
    "answer",
    [
        {**GOOD, "action": "login"},
        {"success": True, "hostname": "testserver"},
        {**GOOD, "hostname": "evil.example"},
        {"success": True, "action": "start"},
    ],
    ids=["another action", "no action", "another host", "no host"],
)
def test_a_token_made_for_another_action_or_on_another_host_is_refused(visitor, cloudflare, answer):
    cloudflare.says(answer)
    assert first_message(visitor).status_code == 403


def test_the_addresses_a_token_may_have_come_from_can_be_set_apart_from_the_hosts_own(
    visitor, backend, cloudflare, settings
):
    settings.TURNSTILE_HOSTNAMES = ["234.example.com"]
    cloudflare.says({**GOOD, "hostname": "234.example.com"})
    assert first_message(visitor).status_code == 200
    cloudflare.says(GOOD)
    assert first_message(visitor).status_code == 403


def test_cloudflares_published_test_keys_return_no_action_and_example_com_and_pass(
    visitor, backend, cloudflare, settings
):
    settings.TURNSTILE_SITE_KEY = "1x00000000000000000000AA"
    cloudflare.says({"success": True, "hostname": "example.com"})
    assert first_message(visitor).status_code == 200


@pytest.mark.parametrize(
    "down",
    [
        httpx.ConnectError("no route"),
        httpx.ReadTimeout("slow"),
        (503, b"upstream unavailable"),
        (500, json.dumps({"success": False}).encode()),
        (200, b"<html>not json</html>"),
        (200, b"[]"),
    ],
)
def test_when_cloudflare_cannot_be_asked_the_message_goes_on_to_the_limits_that_were_always_there(
    visitor, backend, cloudflare, down
):
    cloudflare.answer = down
    assert first_message(visitor).status_code == 200
    assert Chat.objects.count() == 1


def test_a_second_message_to_a_chat_that_exists_needs_no_token(visitor, backend, cloudflare):
    chat_id = visitor.new_chat()
    assert first_message(visitor, None, chat_id=chat_id).status_code == 200
    assert cloudflare.asked == []


def test_a_message_to_a_chat_that_is_not_the_visitors_still_needs_a_token(visitor, cloudflare):
    chat_id = secrets.token_hex(16)
    assert first_message(visitor, None, chat_id=chat_id).status_code == 403


def test_the_other_ways_into_a_chat_are_not_asked_for_a_token(visitor, backend, cloudflare):
    chat_id = visitor.new_chat()
    assert visitor.post(f"/c/{chat_id}/send", json={"text": "hello"}).status_code == 200
    assert cloudflare.asked == []


def test_a_deploys_smoke_test_holds_the_ops_token_and_passes_but_a_wrong_one_does_not(
    visitor, backend, cloudflare, settings
):
    settings.OPS_TOKEN = "ops-token-of-this-deploy"
    assert (
        first_message(visitor, None, HTTP_AUTHORIZATION="Bearer ops-token-of-this-deploy").status_code == 200
    )
    assert cloudflare.asked == []
    assert first_message(visitor, None, HTTP_AUTHORIZATION="Bearer another").status_code == 403
    settings.OPS_TOKEN = ""
    assert first_message(visitor, None, HTTP_AUTHORIZATION="Bearer ").status_code == 403, (
        "no token set, none passes"
    )


def test_a_signed_in_person_passes_nothing_and_is_not_offered_the_widget(
    sign_in_on, key, backend, cloudflare
):
    from .account_support import Device

    person = Device()
    assert person.sign_in(key).status_code == 200
    assert person.client.get("/api/me").json()["botCheck"] is None
    answer = person.post(f"/c/{secrets.token_hex(16)}/start", {"text": "hello"})
    assert answer.status_code == 200 and cloudflare.asked == []


def test_a_visitor_is_given_the_site_key_and_never_the_secret(client, cloudflare):
    answer = client.get("/api/me")
    assert answer.json()["botCheck"] == KEY and SECRET not in answer.content.decode()


def test_without_turnstile_the_page_is_told_of_none(client):
    assert client.get("/api/me").json()["botCheck"] is None


def test_the_policy_lets_the_page_reach_cloudflare_only_where_turnstile_is_on(settings, cloudflare):
    on = {d.split(" ")[0]: d for d in page_policy().split("; ")}
    for name in ("script-src", "connect-src", "frame-src"):
        assert "https://challenges.cloudflare.com" in on[name]
    settings.TURNSTILE_ENABLED = False
    assert "challenges.cloudflare.com" not in page_policy()


def test_the_policy_keeps_what_sign_in_adds_when_both_are_on(sign_in_on, cloudflare):
    policy = {d.split(" ")[0]: d for d in page_policy().split("; ")}
    assert "https://apis.google.com" in policy["script-src"]
    assert "https://challenges.cloudflare.com" in policy["script-src"]
    assert "https://demo.firebaseapp.com" in policy["frame-src"]
    assert "https://challenges.cloudflare.com" in policy["frame-src"]
