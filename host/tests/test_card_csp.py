# SPDX-License-Identifier: AGPL-3.0-or-later
"""What a card's resource may ask of the sandbox: every entry checked, the host's allowlist applied, what is
refused logged and never shown, and the JSON the page gets."""

import json
import logging
import subprocess
import sys
from pathlib import Path

import pytest

from chat import card_csp, sandbox
from chat.card_csp import FIELDS, MAX_ENTRIES, OriginPolicy, refusal, resolve

VECTORS = json.loads((Path(__file__).parents[2] / "sandbox/test/csp-vectors.json").read_text())
PAYSTACK = {"resourceDomains": ["https://js.paystack.co"], "frameDomains": ["https://checkout.paystack.com"]}
NOTHING = frozenset()


def policy_for_paystack() -> OriginPolicy:
    return OriginPolicy({name: frozenset(PAYSTACK.get(name, ())) for name in FIELDS})


@pytest.mark.parametrize(("name", "entry"), VECTORS["accepted"])
def test_a_declarable_source_is_accepted(name, entry):
    assert refusal(name, entry) is None


@pytest.mark.parametrize(("name", "entry"), VECTORS["refused"])
def test_any_other_source_is_refused(name, entry):
    assert isinstance(refusal(name, entry), str)


def test_the_paystack_card_gets_its_two_origins_and_nothing_else():
    asked = {"csp": {**PAYSTACK, "connectDomains": ["https://api.paystack.co"]}}
    declaration = resolve(asked, "paystack-pay", policy_for_paystack(), NOTHING)
    assert declaration.csp == PAYSTACK
    assert [(r.field, r.entry, r.reason) for r in declaration.refused] == [
        ("connectDomains", "https://api.paystack.co", "not on this host's allowlist")
    ]
    assert declaration.hosts == ["js.paystack.co", "checkout.paystack.com"]


def test_an_origin_is_allowed_for_the_field_the_host_named_and_no_other():
    asked = {
        "csp": {
            "frameDomains": ["https://js.paystack.co"],
            "resourceDomains": ["https://checkout.paystack.com"],
        }
    }
    assert resolve(asked, "s", policy_for_paystack(), NOTHING).csp == {}


def test_a_compromised_connector_gets_nothing_outside_the_allowlist():
    asked = {
        "csp": {name: ["https://evil.example.com", "*", "https://*.evil.example.com"] for name in FIELDS}
    }
    declaration = resolve(asked, "food-order", policy_for_paystack(), NOTHING)
    assert declaration.csp == {}
    assert len(declaration.refused) == 4 * 3


def test_the_image_origins_of_a_trusted_connector_are_taken_as_plain_origins():
    trusted = OriginPolicy({}, {"food-order": frozenset({"resourceDomains"})})
    images = ["https://cdn.merchant.example", "https://*.merchant.example", "data:"]
    asked = {"csp": {"resourceDomains": images, "connectDomains": ["https://cdn.merchant.example"]}}
    kept = resolve(asked, "food-order", trusted, NOTHING)
    assert kept.csp == {"resourceDomains": ["https://cdn.merchant.example"]}
    assert {r.entry for r in kept.refused} == {
        "https://*.merchant.example",
        "data:",
        "https://cdn.merchant.example",
    }
    assert resolve(asked, "paystack-pay", trusted, NOTHING).csp == {}


def test_at_most_sixteen_entries_a_field_and_a_repeat_counts_once():
    origins = [f"https://img{n}.example.com" for n in range(20)]
    everything = OriginPolicy({"resourceDomains": frozenset(origins)})
    declaration = resolve({"csp": {"resourceDomains": [*origins, origins[0]]}}, "s", everything, NOTHING)
    assert declaration.csp["resourceDomains"] == origins[:MAX_ENTRIES]
    assert len(declaration.refused) == 5


@pytest.mark.parametrize(
    "csp",
    [None, 7, "x", [], {"resourceDomains": "https://js.paystack.co"}, {"resourceDomains": [None, 3, {}]}],
)
def test_a_declaration_that_is_not_the_shape_asked_for_narrows_to_nothing(csp):
    assert resolve({"csp": csp}, "s", policy_for_paystack(), NOTHING).csp == {}
    assert (
        resolve(
            {"csp": csp, "permissions": csp, "domain": csp, "prefersBorder": csp},
            "s",
            policy_for_paystack(),
            NOTHING,
        ).permissions
        == {}
    )


def test_permissions_are_granted_only_when_asked_and_allowed():
    asked = {"permissions": {"camera": {}, "clipboardWrite": {}, "geolocation": {}, "payment": {}}}
    assert resolve(asked, "s", OriginPolicy(), NOTHING).permissions == {}
    granted = resolve(asked, "s", OriginPolicy(), frozenset({"clipboardWrite", "microphone"}))
    assert granted.permissions == {"clipboardWrite": {}}


def test_a_domain_and_a_border_preference_are_read_and_the_domain_is_only_noted():
    declaration = resolve({"domain": "abc.example.com", "prefersBorder": True}, "s", OriginPolicy(), NOTHING)
    assert (declaration.domain, declaration.prefers_border) == ("abc.example.com", True)
    assert resolve({"prefersBorder": "yes"}, "s", OriginPolicy(), NOTHING).prefers_border is None


def test_a_card_runs_on_the_sandbox_origin_only_when_it_embeds_an_approved_frame():
    embedding = resolve({"csp": PAYSTACK}, "s", policy_for_paystack(), NOTHING)
    assert embedding.sandbox == "allow-scripts allow-same-origin"
    assert (
        resolve(
            {"csp": {"resourceDomains": PAYSTACK["resourceDomains"]}}, "s", policy_for_paystack(), NOTHING
        ).sandbox
        == "allow-scripts"
    )
    assert (
        resolve(
            {"csp": {"frameDomains": ["https://evil.example.com"]}}, "s", policy_for_paystack(), NOTHING
        ).sandbox
        == "allow-scripts"
    )
    assert resolve({}, "s", policy_for_paystack(), NOTHING).sandbox == "allow-scripts"


def test_the_hosts_shown_lose_scheme_and_port_and_repeat_nothing():
    csp = {
        "connectDomains": ["wss://live.example.com:9000"],
        "resourceDomains": ["https://live.example.com", "https://*.cdn.example.com"],
    }
    assert card_csp.hosts_of(csp) == ["live.example.com", "*.cdn.example.com"]


def test_what_is_refused_is_logged_and_what_is_granted_too(caplog):
    caplog.set_level(logging.INFO, logger="chat.cards")
    asked = {
        "csp": {"resourceDomains": ["https://js.paystack.co", "data:"]},
        "permissions": {"camera": {}},
        "domain": "d.example.com",
    }
    declaration = resolve(asked, "paystack-pay", policy_for_paystack(), NOTHING)
    card_csp.audit("paystack-pay", "ui://paystack-pay/card.html", declaration, asked)
    lines = [json.loads(r.message) for r in caplog.records]
    assert [line["event"] for line in lines] == ["card.csp", "card.csp.refused"]
    assert lines[0]["csp"] == {"resourceDomains": ["https://js.paystack.co"]} and lines[0][
        "asked_permissions"
    ] == ["camera"]
    assert lines[0]["permissions"] == [] and lines[0]["domain_ignored"] == "d.example.com"
    assert lines[1]["entry"] == "data:" and lines[1]["server"] == "paystack-pay"


def test_the_paystack_origins_follow_the_switch(settings):
    settings.INLINE_PAYSTACK = True
    assert sandbox.origin_policy().approved() == {name: sorted(PAYSTACK[name]) for name in PAYSTACK}
    settings.INLINE_PAYSTACK = False
    assert sandbox.origin_policy().approved() == {}
    settings.CARD_ALLOWED_ORIGINS = ["https://extra.example.com"]
    assert sandbox.origin_policy().approved()["frameDomains"] == ["https://extra.example.com"]


def test_the_host_tells_a_view_what_it_grants(settings):
    settings.INLINE_PAYSTACK = True
    settings.CARD_GRANTED_PERMISSIONS = []
    assert sandbox.host_sandbox() == {
        "permissions": {},
        "csp": {name: sorted(PAYSTACK[name]) for name in PAYSTACK},
    }
    settings.CARD_GRANTED_PERMISSIONS = ["clipboardWrite", "nonsense"]
    assert sandbox.host_sandbox()["permissions"] == {"clipboardWrite": {}}


SIGNATURE = json.loads((Path(__file__).parents[2] / "sandbox/test/signature-vector.json").read_text())


@pytest.fixture(autouse=True)
def signing_key(monkeypatch):
    monkeypatch.setenv("SANDBOX_SIGNING_KEY", "test-signing-key")


def test_the_signature_is_the_one_the_sandbox_checks(monkeypatch):
    monkeypatch.setenv("SANDBOX_SIGNING_KEY", SIGNATURE["key"])
    assert sandbox.canonical(SIGNATURE["host"], SIGNATURE["csp"]) == SIGNATURE["canonical"]
    assert sandbox.sign(SIGNATURE["host"], SIGNATURE["csp"]) == SIGNATURE["signature"]
    assert sandbox.sign(SIGNATURE["host"], {}) != SIGNATURE["signature"]
    assert sandbox.sign("https://234.example.com", SIGNATURE["csp"]) != SIGNATURE["signature"]


@pytest.mark.django_db
def test_a_host_without_a_signing_key_shows_no_card(visitor, backend, monkeypatch):
    monkeypatch.delenv("SANDBOX_SIGNING_KEY")
    chat_id = visitor.new_chat()
    page = visitor.client.get(f"/c/{chat_id}/card", {"server": "s", "uri": "ui://s/card.html"})
    assert page.status_code == 503 and "signing key" in page.json()["error"]


@pytest.mark.django_db
def test_the_card_route_answers_json_with_what_the_host_grants(visitor, backend, settings):
    settings.INLINE_PAYSTACK = True
    chat_id = visitor.new_chat()
    backend.ui = {"csp": {**PAYSTACK, "connectDomains": ["https://evil.example.com"]}, "prefersBorder": False}
    page = visitor.client.get(f"/c/{chat_id}/card", {"server": "s", "uri": "ui://s/card.html"})
    card = page.json()
    assert page.status_code == 200 and page["Content-Type"] == "application/json"
    assert card["csp"] == PAYSTACK and card["hosts"] == ["js.paystack.co", "checkout.paystack.com"]
    assert card["permissions"] == {} and card["prefersBorder"] is False
    assert card["sandbox"] == "allow-scripts allow-same-origin"
    assert (
        card["signature"] == sandbox.sign("http://testserver", card["csp"]) and len(card["signature"]) == 64
    )
    assert card["html"].startswith('<meta name="color-scheme" content="light dark">')
    assert page["Cache-Control"] == "private, max-age=300"


@pytest.mark.django_db
def test_the_signature_is_for_the_origin_the_page_was_reached_at(visitor, backend, settings):
    settings.ALLOWED_HOSTS = ["testserver", "234.example.com"]
    chat_id = visitor.new_chat()
    asked = {"server": "s", "uri": "ui://s/card.html"}
    custom = visitor.client.get(f"/c/{chat_id}/card", asked, HTTP_HOST="234.example.com").json()
    own = visitor.client.get(f"/c/{chat_id}/card", asked).json()
    assert custom["signature"] == sandbox.sign("http://234.example.com", {})
    assert own["signature"] == sandbox.sign("http://testserver", {}) != custom["signature"]


@pytest.mark.django_db
def test_a_card_that_declares_nothing_asks_the_person_nothing(visitor, backend):
    chat_id = visitor.new_chat()
    card = visitor.client.get(f"/c/{chat_id}/card", {"server": "s", "uri": "ui://s/card.html"}).json()
    assert card["csp"] == {} and card["hosts"] == [] and card["prefersBorder"] is None


@pytest.mark.django_db
def test_the_card_route_is_the_visitors_own(visitor, other_chat):
    assert (
        visitor.client.get(f"/c/{other_chat.id}/card", {"server": "s", "uri": "ui://s/card.html"}).status_code
        == 404
    )


@pytest.mark.django_db
def test_a_refused_card_is_a_400_with_a_reason(visitor, backend):
    from turns.hub import HubError

    def refuse(server, uri):
        raise HubError("s declares no card at x.")

    backend.card_page = refuse
    chat_id = visitor.new_chat()
    page = visitor.client.get(f"/c/{chat_id}/card", {"server": "s", "uri": "x"})
    assert page.status_code == 400 and "declares no card" in page.json()["error"]


@pytest.mark.django_db
def test_a_page_may_frame_only_the_sandbox(visitor, settings):
    settings.SANDBOX_ORIGIN = "https://sandbox.example.com"
    page = visitor.client.get("/")
    assert "frame-src https://sandbox.example.com;" in page["Content-Security-Policy"]
    assert 'data-sandbox-origin="https://sandbox.example.com"' in page.content.decode()
    assert "&quot;csp&quot;" in page.content.decode()


def test_the_sandbox_cannot_be_the_hosts_own_origin():
    code = "import config.settings"
    env = {
        "PATH": "",
        "DJANGO_DEBUG": "1",
        "SANDBOX_ORIGIN": "http://localhost:8790",
        "PUBLIC_BASE_URL": "http://localhost:8790",
    }
    result = subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        cwd=Path(__file__).parents[1] / "src",
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0 and "different origin" in result.stderr
