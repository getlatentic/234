# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the public deployment's configuration (wrangler.public.jsonc) makes the connectors do: nothing that
reaches Paystack or VTpass, no test routes, and no tools for a caller without the token."""

import json
import re
from pathlib import Path

import pytest

from checkout.config import CONNECTORS, Settings
from checkout.errors import ConfigError
from tests.keys import fake_key

TEMPLATE = Path(__file__).resolve().parents[1] / "wrangler.public.jsonc"
SECRETS = {"APPROVAL_SECRET": "x-not-real", "MCP_ACCESS_TOKEN": "t" * 40}


def public_template() -> dict:
    text = "\n".join(line for line in TEMPLATE.read_text().splitlines() if not line.strip().startswith("//"))
    return json.loads(re.sub(r"@[A-Z_]+@", "name", text))


def public_vars() -> dict[str, str]:
    return public_template()["vars"]


def load(**more: str) -> Settings:
    return Settings.from_env({**public_vars(), **SECRETS, **more}.get)


def test_every_connector_is_simulated_and_no_provider_key_is_carried():
    settings = load()
    assert [settings.paystack.mode_for(c) for c in CONNECTORS] == ["simulated"] * len(CONNECTORS)
    assert settings.paystack.secret_key is None
    assert (settings.vtpass.mode, settings.vtpass.credentials) == ("simulated", None)


def test_a_paystack_test_key_or_vtpass_credentials_set_by_mistake_change_nothing():
    settings = load(
        PAYSTACK_TEST_SECRET_KEY=fake_key("test"),
        VTPASS_API_KEY="a",
        VTPASS_PUBLIC_KEY="PK_b",
        VTPASS_SECRET_KEY="SK_c",
    )
    assert settings.paystack.secret_key is None
    assert [settings.paystack.mode_for(c) for c in CONNECTORS] == ["simulated"] * len(CONNECTORS)
    assert (settings.vtpass.mode, settings.vtpass.credentials) == ("simulated", None)


def test_the_public_configuration_never_names_live_vtpass_and_refuses_it_when_asked():
    assert public_vars()["VTPASS_MODE"] == "simulated"
    for keys in ({}, {"VTPASS_API_KEY": "a", "VTPASS_PUBLIC_KEY": "PK_b", "VTPASS_SECRET_KEY": "SK_c"}):
        with pytest.raises(ConfigError, match="VTPASS_MODE=live is refused"):
            load(VTPASS_MODE="live", **keys)


def test_the_public_deployment_reaches_the_hosts_event_callbacks_through_its_service_binding():
    assert load().host_binding == "HOST"
    assert load().host_public_url == "https://name.name.workers.dev"
    assert public_template()["services"] == [{"binding": "HOST", "service": "name"}]


def test_a_live_key_stops_the_worker_at_startup():
    with pytest.raises(ConfigError, match="live key"):
        load(PAYSTACK_TEST_SECRET_KEY=fake_key("live"))
    with pytest.raises(ConfigError, match="live key"):
        load(PAYSTACK_SECRET_KEY=fake_key("live"))


def test_the_test_routes_are_off():
    assert load().enable_test_routes is False


def test_the_tools_need_the_token_and_the_worker_does_not_start_without_one():
    assert load().mcp_token == SECRETS["MCP_ACCESS_TOKEN"]
    without = {**public_vars(), "APPROVAL_SECRET": "x-not-real"}
    with pytest.raises(ConfigError, match="MCP_ACCESS_TOKEN"):
        Settings.from_env(without.get)


def test_every_tool_call_must_name_its_owner_so_each_visitor_has_their_own_daily_limit():
    assert load().require_owner is True
    assert Settings.from_env({"APPROVAL_SECRET": "x-not-real"}.get).require_owner is False


def test_the_simulators_run_their_ordinary_paths_and_the_limits_are_the_demo_limits():
    settings = load()
    assert settings.simulator.transfer_otp is False
    assert (settings.per_payment_limit_kobo, settings.daily_limit_kobo) == (5_000_000, 10_000_000)


def test_the_public_deployment_queues_rechecks_and_deliveries_with_dead_letter_queues():
    queues = public_template()["queues"]
    assert {p["binding"] for p in queues["producers"]} == {"PROVIDER_JOBS", "EVENT_JOBS"}
    assert all(c["dead_letter_queue"].endswith("-dlq") and c["max_retries"] >= 1 for c in queues["consumers"])
    assert public_template()["triggers"] == {"crons": ["* * * * *"]}
