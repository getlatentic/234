# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the public deployment's configuration (wrangler.public.jsonc) sets for the host."""

import json
import re
from pathlib import Path

from turns.settings import Settings

TEMPLATE = Path(__file__).resolve().parents[1] / "wrangler.public.jsonc"


def public_config() -> dict:
    text = "\n".join(line for line in TEMPLATE.read_text().splitlines() if not line.strip().startswith("//"))
    return json.loads(re.sub(r"@[A-Z_]+@", "name", text))


def settings() -> Settings:
    return Settings.from_env(public_config()["vars"].get)


def test_the_model_is_capped_for_everyone_and_for_each_visitor():
    found = settings()
    assert (found.model_calls_per_day, found.visitor_model_calls_per_day) == (300, 30)


def test_the_model_settings_are_secrets_not_variables():
    variables = public_config()["vars"]
    assert not [name for name in variables if name.startswith("LLM_")]
    assert settings().model_problem() == "No model is configured. Set LLM_BASE_URL and LLM_API_KEY."


def test_the_connectors_are_reached_through_a_service_binding_that_the_config_declares():
    config = public_config()
    binding = config["vars"]["CHECKOUT_MCP_BINDING"]
    assert [s["binding"] for s in config["services"]] == [binding]
    assert settings().mcp_binding == binding


def test_django_runs_without_debug_and_no_other_agent_may_call():
    variables = public_config()["vars"]
    assert variables["DJANGO_DEBUG"] == "0"
    assert "A2A_TOKENS" not in variables and not variables.get("A2A_CORS_ORIGINS")


def test_the_page_is_reachable_only_under_its_own_name():
    variables = public_config()["vars"]
    assert variables["DJANGO_ALLOWED_HOSTS"] == "name.name.workers.dev"
    assert "*" not in variables["DJANGO_ALLOWED_HOSTS"]


def test_the_worker_is_public_on_workers_dev_only():
    config = public_config()
    assert config["workers_dev"] is True and config["preview_urls"] is False
    assert "routes" not in config


def test_all_four_connectors_are_named():
    assert set(public_config()["vars"]["CONNECTORS"].split(",")) == {
        "paystack-pay",
        "send-money",
        "airtime",
        "food-order",
    }


def rendered(**names: str) -> dict:
    """The template with each @NAME@ filled in from `names`, and any other left as "name"."""
    text = "\n".join(line for line in TEMPLATE.read_text().splitlines() if not line.strip().startswith("//"))
    text = re.sub(r"@([A-Z_]+)@", lambda found: names.get(found.group(1), "name"), text)
    return json.loads(text)


def test_the_cards_are_framed_by_a_sandbox_on_its_own_hostname():
    variables = rendered(HOST_WORKER="chat", SANDBOX_WORKER="chat-sandbox", SUBDOMAIN="acct")["vars"]
    assert variables["SANDBOX_ORIGIN"] == "https://chat-sandbox.acct.workers.dev"
    assert variables["PUBLIC_BASE_URL"] == "https://chat.acct.workers.dev"
    assert variables["SANDBOX_ORIGIN"] != variables["PUBLIC_BASE_URL"]


def test_no_card_may_use_a_browser_feature_and_the_paystack_switch_is_left_on():
    variables = public_config()["vars"]
    assert not variables.get("CARD_GRANTED_PERMISSIONS")
    assert variables.get("INLINE_PAYSTACK", "1") == "1"


def test_the_public_deployment_offers_every_connector_the_product_has():
    assert settings().connectors == Settings(mcp_url="").connectors
