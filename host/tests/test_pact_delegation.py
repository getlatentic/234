# SPDX-License-Identifier: AGPL-3.0-or-later
"""PACT 1.0, Delegated profile (§5): the card's device-code scheme and the RFC 8414 metadata, device
authorization bound to the agent's User, the person's sign-in and consent, the delegation token and its
refresh, messages that run as the person's account within the granted scopes, receipts verified with the
published key, step-up, and every refusal a delegation token can meet."""

import hashlib
import json
import time
from urllib.parse import urlencode, urlsplit

import pytest

from chat.models import Chat
from pact.models import Context, DeviceAuthorization, Grant
from turns import kinds

from .account_support import Device
from .pact_support import (
    ISSUER,
    Agent,
    call,
    envelope,
    host_signing_key,
    message,
    pact_installed,
    verified_by,
)

pytestmark = pytest.mark.django_db
BRANDS = json.dumps({
    "234": {"name": "234", "description": "Everything"},
    "food": {"name": "Mama Put", "description": "Food only", "connectors": ["food-order"]},
})  # fmt: skip
OAUTH = "/a2a/234/oauth"
EVERY_SCOPE = "memory:read memory:write payments"
DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
FORM = "application/x-www-form-urlencoded"


@pytest.fixture(scope="module")
def agent():
    return Agent()


@pytest.fixture(scope="module")
def host_key():
    return host_signing_key()


@pytest.fixture(autouse=True)
def pact_on(settings, monkeypatch, agent, backend, host_key):
    settings.PACT_SIGNING_KEY = host_key
    with pact_installed(settings, monkeypatch, agent, backend, BRANDS):
        yield


@pytest.fixture
def person(sign_in_on, key):
    device = Device()
    assert device.sign_in(key).status_code == 200
    return device


def account_of(device: Device) -> str:
    return device.client.get("/api/me").wsgi_request.account.owner


def form(client, agent, path, fields, token="default", client_id=ISSUER):
    token = agent.token() if token == "default" else token
    headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"} if token else {}
    body = {"client_id": client_id, **fields} if client_id else fields
    return client.post(f"{OAUTH}/{path}", urlencode(body), FORM, **headers)


def start(client, agent, scope=EVERY_SCOPE, **changes):
    return form(client, agent, "device_authorization", {"scope": scope}, **changes)


def poll(client, agent, device_code, **changes):
    grant = {"grant_type": DEVICE_GRANT, "device_code": device_code}
    return form(client, agent, "token", grant, **changes)


def decide(person, user_code, scopes, decision="allow"):
    return person.client.post(
        f"{OAUTH}/device", {"user_code": user_code, "decision": decision, "scope": scopes}
    )


def ready_to_poll(device_code):
    DeviceAuthorization.objects.update(polled_at=0)
    return device_code


def granted(client, agent, person, scopes=("memory:read", "payments"), sub="user-1"):
    started = start(client, agent, token=agent.token(sub=sub)).json()
    assert decide(person, started["user_code"], list(scopes)).status_code == 200
    return poll(client, agent, started["device_code"], token=agent.token(sub=sub)).json()


def delegated(client, agent, token, body, sub="user-1", **headers):
    return call(
        client, agent, "message:send", body=body, token=agent.token(sub=sub),
        HTTP_X_A2A_USER_DELEGATION=f"Bearer {token}", **headers,
    )  # fmt: skip


def jwks(client):
    return client.get(f"{OAUTH}/jwks.json").json()


def test_without_sign_in_or_a_key_the_card_offers_identity_only_and_the_endpoints_are_404(client, settings):
    for card_of in ("/a2a/234/.well-known/agent-card.json",):
        assert "userDelegation" not in client.get(card_of).json()["securitySchemes"]
    assert client.get(f"{OAUTH}/.well-known/oauth-authorization-server").status_code == 404
    settings.SIGN_IN_ENABLED, settings.PACT_SIGNING_KEY = True, ""
    assert client.get(f"{OAUTH}/jwks.json").status_code == 404


def test_the_card_offers_the_device_code_flow_with_the_brands_own_scopes_and_keeps_identity_alone(
    sign_in_on, client
):
    card = client.get("/a2a/234/.well-known/agent-card.json").json()
    flow = card["securitySchemes"]["userDelegation"]["oauth2SecurityScheme"]
    assert sorted(flow["flows"]["deviceCode"]["scopes"]) == ["memory:read", "memory:write", "payments"]
    assert card["securityRequirements"] == [
        {"schemes": {"paJwt": {"list": []}}},
        {"schemes": {"paJwt": {"list": []}, "userDelegation": {"list": []}}},
    ]
    food = client.get("/a2a/food/.well-known/agent-card.json").json()["securitySchemes"]["userDelegation"]
    assert list(food["oauth2SecurityScheme"]["flows"]["deviceCode"]["scopes"]) == ["payments"]
    metadata = client.get(urlsplit(flow["oauth2MetadataUrl"]).path).json()
    assert metadata["device_authorization_endpoint"] == flow["flows"]["deviceCode"]["deviceAuthorizationUrl"]
    assert metadata["token_endpoint"] == flow["flows"]["deviceCode"]["tokenUrl"]
    assert metadata["issuer"].endswith("/a2a/234/oauth") and metadata["jwks_uri"].endswith("/jwks.json")


def test_device_authorization_needs_the_agents_jwt_its_issuer_as_client_id_and_known_scopes(
    sign_in_on, client, agent
):
    assert start(client, agent, token=None).status_code == 401
    assert start(client, agent, token=agent.token(aud="someone-else")).status_code == 401
    wrong = start(client, agent, client_id="https://other.example")
    assert wrong.status_code == 401 and wrong.json()["error"] == "invalid_client"
    for scope in ("flights:rebook", "", "memory:read payments:everything"):
        assert start(client, agent, scope=scope).json()["error"] == "invalid_scope"
    started = start(client, agent).json()
    assert started["interval"] == 5 and started["expires_in"] == 600
    assert (
        started["verification_uri_complete"]
        == f"{started['verification_uri']}?user_code={started['user_code']}"
    )
    assert started["device_code"] not in json.dumps(list(DeviceAuthorization.objects.values()))


def test_the_page_asks_a_signed_out_person_to_sign_in_before_it_shows_any_consent(sign_in_on, client, agent):
    started = start(client, agent).json()
    page = Device().client.get(
        urlsplit(started["verification_uri_complete"]).path, {"user_code": started["user_code"]}
    )
    assert page.status_code == 200 and b"Sign in to connect your agent" in page.content
    assert b'name="decision"' not in page.content
    refused = Device().client.post(
        f"{OAUTH}/device", {"user_code": started["user_code"], "decision": "allow"}
    )
    assert refused.status_code == 403 and DeviceAuthorization.objects.get().status == "pending"


def test_consent_names_the_agent_and_shows_each_scope_as_the_brand_describes_it(person, client, agent):
    started = start(client, agent).json()
    page = person.client.get(f"{OAUTH}/device", {"user_code": started["user_code"].lower().replace("-", "")})
    text = page.content.decode()
    assert "Allow pa.example to act for you at 234?" in text and started["user_code"] in text
    from turns.permissions import SCOPES

    for scope, description in SCOPES.items():
        assert f'value="{scope}" checked' in text and description in text


def test_a_token_is_issued_once_for_only_the_scopes_the_person_left_ticked(person, client, agent):
    started = start(client, agent).json()
    assert poll(client, agent, started["device_code"]).json()["error"] == "authorization_pending"
    assert poll(client, agent, started["device_code"]).json()["error"] == "slow_down"
    done = decide(person, started["user_code"], ["memory:read", "payments"])
    assert b"Go back to your agent" in done.content
    answer = poll(client, agent, ready_to_poll(started["device_code"]))
    tokens = answer.json()
    assert answer.status_code == 200 and answer["Cache-Control"] == "no-store"
    assert tokens["scope"] == "memory:read payments" and tokens["token_type"] == "Bearer"
    claims = verified_by(jwks(client), tokens["access_token"])
    assert claims["sub"] == account_of(person) and claims["client_id"] == ISSUER
    assert claims["aud"].endswith("/a2a/234") and claims["iss"].endswith("/a2a/234/oauth")
    assert claims["exp"] - claims["iat"] == tokens["expires_in"] <= 3600
    assert claims["grant_id"] == Grant.objects.get().id
    assert poll(client, agent, started["device_code"]).json()["error"] == "invalid_grant"


def test_a_device_code_is_useless_to_another_user_of_the_agent_or_another_brand(person, client, agent):
    started = start(client, agent).json()
    decide(person, started["user_code"], ["payments"])
    assert poll(client, agent, started["device_code"], token=agent.token(sub="user-2")).json()["error"] == (
        "invalid_grant"
    )
    grant = {"grant_type": DEVICE_GRANT, "device_code": started["device_code"], "client_id": ISSUER}
    other_brand = client.post(
        "/a2a/food/oauth/token", urlencode(grant), FORM, HTTP_AUTHORIZATION=f"Bearer {agent.token()}"
    )
    assert other_brand.json()["error"] == "invalid_grant"
    assert "access_token" in poll(client, agent, started["device_code"]).json()


def test_a_refusal_or_unticking_everything_is_access_denied_and_an_old_code_expired(person, client, agent):
    for decision, scopes in (("deny", ["payments"]), ("allow", [])):
        started = start(client, agent).json()
        assert b"Nothing was allowed" in decide(person, started["user_code"], scopes, decision).content
        assert poll(client, agent, started["device_code"]).json()["error"] == "access_denied"
    started = start(client, agent).json()
    DeviceAuthorization.objects.filter(user_code=started["user_code"]).update(expires_at=int(time.time()) - 1)
    assert b"That code has expired" in decide(person, started["user_code"], ["payments"]).content
    assert poll(client, agent, ready_to_poll(started["device_code"])).json()["error"] == "expired_token"


def test_a_refresh_token_works_once_and_used_twice_ends_the_grant(person, client, agent):
    tokens = granted(client, agent, person)
    grant = {"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"]}
    assert (
        form(client, agent, "token", grant, token=agent.token(sub="user-2")).json()["error"]
        == "invalid_grant"
    )
    fresh = form(client, agent, "token", grant).json()
    assert fresh["scope"] == tokens["scope"] and fresh["refresh_token"] != tokens["refresh_token"]
    assert form(client, agent, "token", grant).json()["error"] == "invalid_grant"
    assert Grant.objects.get().revoked
    assert delegated(client, agent, fresh["access_token"], message("hi")).status_code == 401


def test_a_delegated_message_runs_as_the_account_within_the_scopes_and_carries_a_verified_receipt(
    person, client, agent, backend
):
    tokens = granted(client, agent, person)
    ran = {"call_id": "c1", "server": "airtime", "tool": "create_airtime_quote", "arguments": {"amount": 200},
           "result_text": "ok", "is_error": False, "scope": "payments"}  # fmt: skip
    backend.tools_for = lambda text, scopes: [(kinds.TOOL, ran)]
    answer = delegated(client, agent, tokens["access_token"], message("buy ₦200 airtime"))
    reply = answer.json()["message"]
    context = Context.objects.get(chat_id=reply["contextId"])
    assert (
        context.account == account_of(person)
        and Chat.objects.get(pk=reply["contextId"]).owner == context.account
    )
    assert backend.scopes[-1] == ["memory:read", "payments"]
    receipt = reply["metadata"]["pact.receipt"]
    claims = verified_by(jwks(client), receipt["jws"])
    assert claims == receipt["claims"]
    assert (
        claims["user"] == context.account and claims["pa"] == ISSUER and claims["brand"].endswith("/a2a/234")
    )
    assert claims["grantId"] == Grant.objects.get().id and claims["scopesUsed"] == ["payments"]
    assert [a["tool"] for a in claims["actions"]] == ["airtime__create_airtime_quote"]
    assert claims["actions"][0]["argsHash"] == hashlib.sha256(b'{"amount":200}').hexdigest()


def test_a_delegation_token_that_does_not_hold_is_401_invalid_token_with_no_body(person, client, agent):
    tokens = granted(client, agent, person)
    good = tokens["access_token"]
    for token, sub in ((good[:-4] + "AAAA", "user-1"), (good, "user-2"), ("not-a-jwt", "user-1")):
        answer = delegated(client, agent, token, message("hi"), sub=sub)
        assert answer.status_code == 401 and answer.content == b""
        assert answer["WWW-Authenticate"] == 'Bearer realm="a2a", error="invalid_token"'
    other_brand = call(
        client,
        agent,
        "message:send",
        body=message("hi"),
        brand="food",
        HTTP_X_A2A_USER_DELEGATION=f"Bearer {good}",
    )
    assert other_brand.status_code == 401
    Grant.objects.update(revoked=True)
    assert delegated(client, agent, good, message("hi")).status_code == 401


@pytest.mark.parametrize(
    "change",
    [
        {"aud": "http://testserver/a2a/food"},
        {"iss": "http://testserver/a2a/food/oauth"},
        {"client_id": "https://other.example"},
        {"exp": 1},
        {"iat": 4_000_000_000},
        {"sub": "u:" + "f" * 32},
    ],
)
def test_a_token_this_host_signed_is_still_refused_when_any_one_claim_is_wrong(person, client, agent, change):
    from pact import signing

    good = granted(client, agent, person)["access_token"]
    claims = verified_by(jwks(client), good)
    assert delegated(client, agent, good, message("hi")).status_code == 200
    assert delegated(client, agent, signing.sign({**claims, **change}), message("hi")).status_code == 401


def test_a_call_needing_a_scope_the_token_lacks_steps_up_and_the_context_carries_on_as_the_account(
    person, client, agent, backend
):
    refused = {"call_id": "c1", "server": "memory", "tool": "recall", "arguments": {}, "result_text": "no",
               "is_error": True, "missing_scopes": ["memory:read"]}  # fmt: skip
    backend.tools_for = lambda text, scopes: [(kinds.TOOL, refused)] if not scopes else []
    first = call(client, agent, "message:send", body=message("send ₦500 to Mum", messageId="m-1")).json()
    task = first["task"]
    assert task["status"]["state"] == "TASK_STATE_AUTH_REQUIRED"
    assert task["metadata"] == {"pact.missingScopes": ["memory:read"]} and backend.scopes[-1] == []
    again_body = message("send ₦500 to Mum", messageId="m-1", contextId=task["contextId"])
    retried = call(client, agent, "message:send", body=again_body).json()
    assert retried == first
    begun_in = Chat.objects.get(pk=task["contextId"])
    tokens = granted(client, agent, person, scopes=("memory:read",))
    again = delegated(
        client, agent, tokens["access_token"], message("send ₦500 to Mum", contextId=task["contextId"])
    )
    reply = again.json()["message"]
    context = Context.objects.get(pk=task["contextId"])
    assert reply["contextId"] == task["contextId"] and "pact.receipt" in reply["metadata"]
    assert Chat.objects.get(pk=begun_in.pk).owner == begun_in.owner, "the first chat keeps its owner"
    assert Chat.objects.get(pk=context.delegated_chat_id).owner == account_of(person)
    assert backend.submitted[-1][0] == context.delegated_chat_id


def test_a_context_that_runs_as_an_account_needs_that_accounts_token(person, client, agent, sign_in_on, key):
    tokens = granted(client, agent, person)
    context = delegated(client, agent, tokens["access_token"], message("hi")).json()["message"]["contextId"]
    plain = call(client, agent, "message:send", body=message("again", contextId=context))
    assert "delegation token" in envelope(plain, 400, "INVALID_ARGUMENT", "INVALID_PARAMS")
    someone = Device()
    assert someone.sign_in(key, uid="uid-other", email="bo@example.com").status_code == 200
    theirs = granted(client, agent, someone)
    other = delegated(client, agent, theirs["access_token"], message("again", contextId=context))
    assert (
        envelope(other, 400, "INVALID_ARGUMENT", "INVALID_PARAMS")
        == "This conversation runs as another 234 account."
    )


def test_the_device_page_needs_its_csrf_token(person, client, agent):
    started = start(client, agent).json()
    person.client.handler.enforce_csrf_checks = True
    assert decide(person, started["user_code"], ["payments"]).status_code == 403
    assert DeviceAuthorization.objects.get().status == "pending"


def test_the_database_keeps_digests_of_device_codes_and_refresh_tokens(person, client, agent):
    tokens = granted(client, agent, person)
    stored = json.dumps(
        [list(DeviceAuthorization.objects.values()), list(Grant.objects.values())], default=str
    )
    from pact.models import RefreshToken

    stored += json.dumps(list(RefreshToken.objects.values("digest")))
    assert tokens["refresh_token"] not in stored and "dc_" not in stored
