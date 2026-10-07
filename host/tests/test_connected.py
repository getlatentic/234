# SPDX-License-Identifier: AGPL-3.0-or-later
"""Connected apps: a signed-in person sees the MCP clients and the personal agents that can act for them,
each with what it can use, and ends any of them at once. Nobody else sees or ends them."""

import base64
import hashlib
import secrets
import time

import pytest

from oauth import grants as oauth_grants
from oauth.models import Client
from pact import brands
from pact import grants as pact_grants
from pact.models import Grant, RefreshToken

from .account_support import Device

pytestmark = pytest.mark.django_db


def s256(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


def account_of(device: Device) -> str:
    return device.client.get("/api/me").wsgi_request.account.owner


@pytest.fixture
def person(sign_in_on, key):
    device = Device()
    assert device.sign_in(key).status_code == 200
    return device


def an_app(owner: str, connector: str = "airtime", name: str = "Claude") -> str:
    """An app (Claude unless named), allowed by `owner`: the access token its grant gives."""
    client_id = f"https://{name.lower()}.example/cimd"
    Client.objects.get_or_create(client_id=client_id, defaults={
        "name": name, "redirect_uris": ["https://claude.ai/cb"], "created_at": 0,
    })  # fmt: skip
    resource = f"http://localhost:8790/mcp/{connector}"
    asked = oauth_grants.Request(
        client_id, owner, "https://claude.ai/cb", s256("v" * 43), resource, "payments"
    )
    code = oauth_grants.issue_code(asked)
    return oauth_grants.redeem_code(code, asked.client_id, asked.redirect_uri, "v" * 43, resource)[
        "access_token"
    ]


def an_agent(owner: str) -> Grant:
    grant = pact_grants.make(
        brands.brands()["234"], "https://pa.example", "p:x", owner, "memory:read payments", int(time.time())
    )
    RefreshToken.objects.create(digest=secrets.token_hex(32), grant=grant, expires_at=grant.expires_at)
    return grant


def listing(device: Device) -> list[dict]:
    return device.client.get("/connected/").json()["connections"]


def test_a_signed_out_visitor_has_no_connected_apps(client):
    assert client.get("/connected/").status_code == 404
    assert Device().post("/connected/end", {"kind": "app", "id": "x"}).status_code == 404


def test_the_person_sees_each_app_and_agent_with_what_it_can_use(person, settings):
    owner = account_of(person)
    an_app(owner, "airtime")
    an_app(owner, "send-money")
    an_agent(owner)
    an_agent("u:" + "f" * 32)
    an_app("u:" + "f" * 32, name="ChatGPT")
    found = listing(person)
    assert [(c["kind"], c["name"]) for c in found] == [("app", "Claude"), ("agent", "pa.example")]
    assert found[0]["uses"] == "Airtime and data, Transfers"
    assert found[1]["uses"].startswith("At 234: read your notes, prepare payments. Since ")


def test_disconnecting_an_app_ends_its_tokens_at_once(person):
    token = an_app(account_of(person))
    assert oauth_grants.access_of(token) is not None
    left = person.post("/connected/end", {"kind": "app", "id": "https://claude.example/cimd"}).json()
    assert left == {"connections": []} and oauth_grants.access_of(token) is None


def test_disconnecting_an_agent_revokes_its_grant_and_drops_its_refresh_tokens(person):
    grant = an_agent(account_of(person))
    person.post("/connected/end", {"kind": "agent", "id": grant.id})
    grant.refresh_from_db()
    assert grant.revoked and not RefreshToken.objects.filter(grant=grant).exists()
    assert listing(person) == []


def test_nobody_ends_another_persons_connections(person, key):
    theirs = an_agent("u:" + "f" * 32)
    token = an_app("u:" + "f" * 32)
    person.post("/connected/end", {"kind": "agent", "id": theirs.id})
    person.post("/connected/end", {"kind": "app", "id": "https://claude.example/cimd"})
    theirs.refresh_from_db()
    assert not theirs.revoked and oauth_grants.access_of(token) is not None
