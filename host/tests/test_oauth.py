# SPDX-License-Identifier: AGPL-3.0-or-later
"""OAuth for the MCP gateway: discovery, registration, client metadata documents, the consent page, codes
with PKCE, tokens bound to one connector, refresh rotation, revocation, and the gateway acting for the
account."""

import base64
import hashlib
import json
import secrets
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from django.test import Client

from accounts.owner import account_owner
from chat.security import page_policy
from oauth import grants
from turns.ledger_owner import ledger_owner

from .account_support import ACCOUNT_KEY, Device

pytestmark = pytest.mark.django_db

BASE = "http://localhost:8790"
CALLBACK = "http://127.0.0.1:33418/callback"
AIRTIME = f"{BASE}/mcp/airtime"
INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}


def pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def registered(client=None, redirect=CALLBACK) -> str:
    answer = (client or Client()).post(
        "/oauth/register",
        json.dumps({"client_name": "Test agent", "redirect_uris": [redirect]}),
        content_type="application/json",
    )
    assert answer.status_code == 201, answer.content
    return answer.json()["client_id"]


def authorize_query(who: str, challenge: str, **changes) -> dict:
    query = {
        "response_type": "code",
        "client_id": who,
        "redirect_uri": CALLBACK,
        "state": "s-1",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "resource": AIRTIME,
    }
    return {k: v for k, v in {**query, **changes}.items() if v is not None}


def allowed(device: Device, query: dict) -> dict:
    """The person presses Allow; the redirect's query."""
    answer = device.client.post("/oauth/authorize", {**query, "decision": "allow"})
    assert answer.status_code == 302, answer.content
    return parse_qs(urlsplit(answer["Location"]).query)


def form_post(path: str, form: dict):
    return Client().post(path, urlencode(form), content_type="application/x-www-form-urlencoded")


def exchange(who: str, code: str, verifier: str, **changes):
    form = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": who,
        "redirect_uri": CALLBACK,
        "code_verifier": verifier,
        "resource": AIRTIME,
        **changes,
    }
    return form_post("/oauth/token", form)


@pytest.fixture
def signed_in(sign_in_on, key):
    device = Device()
    assert device.sign_in(key).status_code == 200
    return device


@pytest.fixture
def granted(signed_in):
    """A registered client with tokens for the airtime connector, approved by the signed-in account."""
    client_id = registered()
    verifier, challenge = pkce()
    code = allowed(signed_in, authorize_query(client_id, challenge))["code"][0]
    tokens = exchange(client_id, code, verifier).json()
    return client_id, tokens


def gateway(token: str | None, path: str = "/mcp/airtime", **headers):
    auth = {"HTTP_AUTHORIZATION": f"Bearer {token}"} if token else {}
    return Client().post(path, json.dumps(INIT), content_type="application/json", **auth, **headers)


def test_everything_is_404_while_sign_in_is_off(client):
    for path in (
        "/.well-known/oauth-authorization-server",
        "/.well-known/oauth-protected-resource/mcp/airtime",
        "/oauth/authorize",
    ):
        assert client.get(path).status_code == 404
    assert client.post("/mcp/airtime").status_code == 404


def test_the_authorization_server_metadata_offers_pkce_s256_documents_and_registration(sign_in_on, client):
    found = client.get("/.well-known/oauth-authorization-server").json()
    assert found["issuer"] == BASE
    assert found["code_challenge_methods_supported"] == ["S256"]
    assert found["client_id_metadata_document_supported"] is True
    assert found["token_endpoint_auth_methods_supported"] == ["none"]
    assert found["registration_endpoint"] == f"{BASE}/oauth/register"
    assert found["authorization_response_iss_parameter_supported"] is True


def test_each_connector_has_its_resource_metadata_and_scope(sign_in_on, client):
    airtime = client.get("/.well-known/oauth-protected-resource/mcp/airtime").json()
    assert airtime == {
        "resource": AIRTIME,
        "authorization_servers": [BASE],
        "scopes_supported": ["payments"],
        "bearer_methods_supported": ["header"],
        "resource_name": "234 airtime",
    }
    assert client.get("/.well-known/oauth-protected-resource/mcp/memory").json()["scopes_supported"] == [
        "memory"
    ]
    assert client.get("/.well-known/oauth-protected-resource/mcp/nope").status_code == 404


def test_the_gateway_challenges_a_call_without_a_token(sign_in_on, backend):
    answer = gateway(None)
    assert answer.status_code == 401
    assert answer["WWW-Authenticate"] == (
        f'Bearer resource_metadata="{BASE}/.well-known/oauth-protected-resource/mcp/airtime", '
        'scope="payments"'
    )
    assert gateway("234at_made-up")["WWW-Authenticate"].startswith('Bearer error="invalid_token"')
    assert backend.relayed == []


def test_a_signed_out_person_is_asked_to_sign_in_first(sign_in_on):
    _, challenge = pkce()
    page = Device().client.get("/oauth/authorize", authorize_query(registered(), challenge)).content.decode()
    assert "Sign in to connect Test agent" in page and "Continue with Google" in page
    assert 'name="decision"' not in page


def test_the_consent_page_names_the_client_what_it_can_do_and_where_it_returns(signed_in):
    _, challenge = pkce()
    page = signed_in.client.get("/oauth/authorize", authorize_query(registered(), challenge)).content.decode()
    assert "Allow Test agent to use 234?" in page
    assert "airtime and data quotes. You approve every purchase." in page
    assert "Returns to 127.0.0.1:33418" in page


def test_allow_returns_a_code_with_the_state_and_issuer_and_the_code_buys_tokens(signed_in):
    client_id = registered()
    verifier, challenge = pkce()
    back = allowed(signed_in, authorize_query(client_id, challenge))
    assert back["state"] == ["s-1"] and back["iss"] == [BASE]
    answer = exchange(client_id, back["code"][0], verifier)
    tokens = answer.json()
    assert answer.status_code == 200 and answer["Cache-Control"] == "no-store"
    assert tokens["token_type"] == "Bearer" and tokens["expires_in"] == 3600 and tokens["scope"] == "payments"
    assert tokens["access_token"].startswith("234at_") and tokens["refresh_token"].startswith("234rt_")


def test_cancel_returns_access_denied_and_no_code(signed_in):
    _, challenge = pkce()
    answer = signed_in.client.post(
        "/oauth/authorize", {**authorize_query(registered(), challenge), "decision": "deny"}
    )
    back = parse_qs(urlsplit(answer["Location"]).query)
    assert back["error"] == ["access_denied"] and "code" not in back


def test_the_consent_form_needs_the_pages_csrf_token(sign_in_on, key):
    strict = Client(enforce_csrf_checks=True)
    _, challenge = pkce()
    answer = strict.post(
        "/oauth/authorize", {**authorize_query(registered(), challenge), "decision": "allow"}
    )
    assert answer.status_code == 403


@pytest.mark.parametrize(
    "changes",
    [
        {"code_challenge": None},
        {"code_challenge_method": "plain"},
        {"resource": None},
        {"resource": f"{BASE}/mcp/elsewhere"},
        {"response_type": "token"},
        {"scope": "memory"},
    ],
)
def test_a_bad_request_from_a_known_client_is_sent_back_as_an_error(signed_in, changes):
    _, challenge = pkce()
    answer = signed_in.client.get("/oauth/authorize", authorize_query(registered(), challenge, **changes))
    back = parse_qs(urlsplit(answer["Location"]).query)
    assert answer.status_code == 302 and back["error"][0] in {
        "invalid_request",
        "invalid_target",
        "unsupported_response_type",
        "invalid_scope",
    }
    assert "code" not in back


@pytest.mark.parametrize(
    "changes", [{"client_id": "234c_unknown"}, {"redirect_uri": "https://evil.example/cb"}]
)
def test_an_unknown_client_or_redirect_is_never_redirected_to(signed_in, changes):
    _, challenge = pkce()
    answer = signed_in.client.get("/oauth/authorize", authorize_query(registered(), challenge, **changes))
    assert answer.status_code == 400 and "Can't connect this app" in answer.content.decode()


def test_a_loopback_redirect_may_name_another_port(signed_in):
    _, challenge = pkce()
    query = authorize_query(registered(), challenge, redirect_uri="http://127.0.0.1:50999/callback")
    assert signed_in.client.get("/oauth/authorize", query).status_code == 200


def test_a_code_works_once_with_its_own_verifier_redirect_client_and_resource(signed_in):
    client_id = registered()
    verifier, challenge = pkce()
    code = allowed(signed_in, authorize_query(client_id, challenge))["code"][0]
    for changes in (
        {"code_verifier": pkce()[0]},
        {"redirect_uri": "http://127.0.0.1:1/x"},
        {"client_id": registered()},
        {"resource": f"{BASE}/mcp/send-money"},
    ):
        assert exchange(client_id, code, verifier, **changes).json() == {"error": "invalid_grant"}
    code = allowed(signed_in, authorize_query(client_id, challenge))["code"][0]
    assert exchange(client_id, code, verifier).status_code == 200
    assert exchange(client_id, code, verifier).json() == {"error": "invalid_grant"}


def test_an_expired_code_is_refused(signed_in, monkeypatch):
    client_id = registered()
    verifier, challenge = pkce()
    code = allowed(signed_in, authorize_query(client_id, challenge))["code"][0]
    real = grants.time.time()
    monkeypatch.setattr("oauth.grants.time.time", lambda: real + grants.CODE_SECONDS + 1)
    assert exchange(client_id, code, verifier).json() == {"error": "invalid_grant"}


def test_the_gateway_acts_for_the_account_and_passes_on_only_mcp_headers(granted, backend):
    _, tokens = granted
    answer = gateway(
        tokens["access_token"],
        HTTP_X_LEDGER_OWNER="f" * 32,
        HTTP_MCP_SESSION_ID="sess-1",
        HTTP_MCP_PROTOCOL_VERSION="2025-11-25",
    )
    assert answer.status_code == 200 and answer["mcp-session-id"] == "sess-2"
    connector, body, headers, owner, notes = backend.relayed[-1]
    assert connector == "airtime" and json.loads(body) == INIT and notes is False
    assert owner == ledger_owner(account_owner("uid-abc", ACCOUNT_KEY))
    assert headers == {"mcp-session-id": "sess-1", "mcp-protocol-version": "2025-11-25"}


def test_a_token_for_one_connector_is_refused_by_another(granted, backend):
    _, tokens = granted
    answer = gateway(tokens["access_token"], "/mcp/send-money")
    assert answer.status_code == 401 and 'error="invalid_token"' in answer["WWW-Authenticate"]
    assert backend.relayed == []


def test_an_expired_access_token_is_refused(granted, monkeypatch):
    _, tokens = granted
    real = grants.time.time()
    monkeypatch.setattr("oauth.grants.time.time", lambda: real + grants.ACCESS_SECONDS + 1)
    assert gateway(tokens["access_token"]).status_code == 401


def test_a_refresh_token_is_replaced_and_one_used_twice_ends_the_grant(granted):
    client_id, tokens = granted
    form = {"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"], "client_id": client_id}
    fresh = form_post("/oauth/token", form).json()
    assert (
        fresh["refresh_token"] != tokens["refresh_token"]
        and gateway(fresh["access_token"]).status_code == 200
    )
    assert form_post("/oauth/token", form).json() == {"error": "invalid_grant"}
    assert gateway(fresh["access_token"]).status_code == 401
    assert gateway(tokens["access_token"]).status_code == 401


def test_revoking_a_token_ends_its_grant(granted):
    _, tokens = granted
    assert form_post("/oauth/revoke", {"token": tokens["refresh_token"]}).status_code == 200
    assert gateway(tokens["access_token"]).status_code == 401
    assert form_post("/oauth/revoke", {"token": "234rt_unknown"}).status_code == 200


def test_the_database_keeps_digests_never_tokens(granted):
    from oauth.models import Token

    _, tokens = granted
    stored = set(Token.objects.values_list("digest", flat=True))
    assert tokens["access_token"] not in stored and grants.digest(tokens["access_token"]) in stored


@pytest.mark.parametrize(
    "uris",
    [
        ["http://example.com/cb"],
        ["https://example.com/cb#x"],
        ["https://user@example.com/cb"],
        [],
        ["cursor://cb"],
        ["https://e.com/" + "a" * 2000],
    ],
)
def test_registration_refuses_redirects_that_are_not_https_or_loopback(sign_in_on, client, uris):
    answer = client.post(
        "/oauth/register", json.dumps({"redirect_uris": uris}), content_type="application/json"
    )
    assert answer.status_code == 400 and answer.json()["error"] == "invalid_redirect_uri"


def test_registration_answers_a_public_client_whatever_it_asked_for(sign_in_on, client):
    asked = {
        "redirect_uris": ["https://agent.example/cb"],
        "token_endpoint_auth_method": "client_secret_post",
    }
    found = client.post("/oauth/register", json.dumps(asked), content_type="application/json").json()
    assert found["token_endpoint_auth_method"] == "none" and "client_secret" not in found


def test_a_client_metadata_document_is_fetched_checked_and_kept(signed_in, monkeypatch):
    url = "https://agent.example/oauth/client.json"
    document = {"client_id": url, "client_name": "Doc agent", "redirect_uris": [CALLBACK]}
    fetched = []

    def fetch(asked):
        fetched.append(asked)
        return 200, {}, json.dumps(document).encode()

    monkeypatch.setattr("oauth.views.fetch", fetch)
    _, challenge = pkce()
    page = signed_in.client.get("/oauth/authorize", authorize_query(url, challenge))
    assert "Allow Doc agent to use 234?" in page.content.decode()
    signed_in.client.get("/oauth/authorize", authorize_query(url, challenge))
    assert fetched == [url]


@pytest.mark.parametrize(
    "document",
    [
        {"client_id": "https://other.example/c.json", "redirect_uris": [CALLBACK]},
        {"client_id": "https://agent.example/c.json", "redirect_uris": ["http://evil.example/cb"]},
        {
            "client_id": "https://agent.example/c.json",
            "redirect_uris": [CALLBACK],
            "token_endpoint_auth_method": "private_key_jwt",
        },
    ],
)
def test_a_client_metadata_document_that_does_not_hold_up_is_refused(signed_in, monkeypatch, document):
    monkeypatch.setattr("oauth.views.fetch", lambda url: (200, {}, json.dumps(document).encode()))
    _, challenge = pkce()
    answer = signed_in.client.get(
        "/oauth/authorize", authorize_query("https://agent.example/c.json", challenge)
    )
    assert answer.status_code == 400


@pytest.mark.parametrize(
    "client_id",
    [
        "https://10.0.0.1/c.json",
        "https://localhost/c.json",
        "https://agent.example/",
        "http://agent.example/c.json",
    ],
)
def test_a_client_id_that_is_not_a_public_https_document_url_is_not_fetched(
    signed_in, monkeypatch, client_id
):
    monkeypatch.setattr("oauth.views.fetch", lambda url: pytest.fail(f"fetched {url}"))
    _, challenge = pkce()
    assert signed_in.client.get("/oauth/authorize", authorize_query(client_id, challenge)).status_code == 400


def test_the_token_and_gateway_endpoints_allow_any_page_origin_without_cookies(sign_in_on, client):
    answer = client.options("/oauth/token", HTTP_ORIGIN="https://inspector.example")
    assert answer.status_code == 204 and answer["Access-Control-Allow-Origin"] == "*"
    assert "Access-Control-Allow-Credentials" not in answer
    assert "www-authenticate" in gateway(None)["Access-Control-Expose-Headers"]


def test_the_token_endpoint_takes_only_a_form(granted):
    client_id, tokens = granted
    body = {"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"], "client_id": client_id}
    answer = Client().post("/oauth/token", json.dumps(body), content_type="application/json")
    assert answer.status_code == 400 and answer.json()["error"] == "invalid_request"


def test_the_consent_page_may_send_its_form_only_to_itself_and_the_clients_redirect(signed_in):
    _, challenge = pkce()
    page = signed_in.client.get("/oauth/authorize", authorize_query(registered(), challenge))
    policy = dict(part.split(" ", 1) for part in page["Content-Security-Policy"].split("; "))
    assert policy["form-action"] == "'self' http://127.0.0.1:33418"
    assert "form-action 'self';" in page_policy()


CLAUDE = {
    "client_id": "https://claude.ai/oauth/mcp-oauth-client-metadata",
    "client_name": "Claude",
    "client_uri": "https://claude.ai",
    "redirect_uris": ["https://claude.ai/api/mcp/auth_callback"],
    "grant_types": ["authorization_code", "refresh_token", "urn:ietf:params:oauth:grant-type:jwt-bearer"],
    "response_types": ["code"],
    "token_endpoint_auth_method": "none",
}


def test_claudes_own_client_metadata_document_is_accepted(signed_in, monkeypatch):
    """The document claude.ai serves (fetched 2026-10-05): it lists a grant this server does not offer."""
    monkeypatch.setattr("oauth.views.fetch", lambda url: (200, {}, json.dumps(CLAUDE).encode()))
    _, challenge = pkce()
    query = authorize_query(CLAUDE["client_id"], challenge, redirect_uri=CLAUDE["redirect_uris"][0])
    page = signed_in.client.get("/oauth/authorize", query)
    assert page.status_code == 200 and "Allow Claude to use 234?" in page.content.decode()
    assert "Returns to claude.ai" in page.content.decode()


def test_no_statement_of_the_authorization_server_locks_rows_d1_refuses_for_update(signed_in, monkeypatch):
    """The path Claude takes, which met D1's refusal of SELECT ... FOR UPDATE live on 2026-10-05 (the suite
    makes SQLite refuse it too: conftest.like_d1)."""
    monkeypatch.setattr("oauth.views.fetch", lambda url: (200, {}, json.dumps(CLAUDE).encode()))
    verifier, challenge = pkce()
    query = authorize_query(CLAUDE["client_id"], challenge, redirect_uri=CLAUDE["redirect_uris"][0])
    assert signed_in.client.get("/oauth/authorize", query).status_code == 200
    later = grants.time.time() + 2 * 24 * 3600
    monkeypatch.setattr("oauth.clients.time.time", lambda: later)
    assert signed_in.client.get("/oauth/authorize", query).status_code == 200, "the document is fetched again"
    answer = signed_in.client.post("/oauth/authorize", {**query, "decision": "allow"})
    code = parse_qs(urlsplit(answer["Location"]).query)["code"][0]
    tokens = exchange(CLAUDE["client_id"], code, verifier, redirect_uri=CLAUDE["redirect_uris"][0]).json()
    form = {
        "grant_type": "refresh_token",
        "refresh_token": tokens["refresh_token"],
        "client_id": CLAUDE["client_id"],
    }
    assert "access_token" in form_post("/oauth/token", form).json()
