# SPDX-License-Identifier: AGPL-3.0-or-later
"""The `merchants` connector as the host knows it (docs/commerce.md): offered to the model with the others,
described in its prompt, reachable by an outside agent with the payments scope, and named on a Brand's
card."""

from oauth import resources
from pact.brands import Brand
from pact.card import document
from turns.permissions import PAYMENTS, scopes_of
from turns.prompt import CAPABILITIES, system_prompt
from turns.settings import Settings, with_directory


def test_the_model_is_offered_the_connector_with_the_others_and_told_what_it_is_for():
    assert "merchants" in Settings.connectors
    prompt = system_prompt(Settings.connectors)
    assert CAPABILITIES["merchants"].does in prompt and CAPABILITIES["merchants"].needs in prompt
    assert "merchants" not in system_prompt(("airtime",)) and "browse_merchants" not in system_prompt(
        ("airtime",)
    )


def test_the_directory_is_offered_only_when_merchants_is_switched_on():
    listed = "paystack-pay,merchants,airtime"

    def offered(flag):
        return Settings.from_env({"CONNECTORS": listed, "MERCHANTS": flag}.get).connectors

    for off in (None, "", "0", "no", "off"):
        assert offered(off) == ("paystack-pay", "airtime")
    for on in ("1", "true", "ON", " yes "):
        assert offered(on) == ("paystack-pay", "merchants", "airtime")
    assert "merchants" not in Settings.from_env(lambda name: None).connectors
    assert with_directory(["merchants"], "1") == ("merchants",)


def test_an_outside_agent_reaches_it_with_the_payments_scope_and_is_told_it_is_asked_to_approve():
    assert resources.scope_of("merchants") == resources.MONEY_SCOPE
    assert resources.name_of("merchants") == "Shops and services"
    assert "You approve every purchase" in resources.what_it_can_do("merchants")
    assert resources.connector_of(resources.resource_url("merchants")) == "merchants"
    assert set(scopes_of(["merchants"])) == {PAYMENTS}


def test_a_brand_with_it_names_the_skill_on_its_card():
    card = document(Brand("shops", "Shops", "Buy from shops", ("merchants",)))
    assert [skill["id"] for skill in card["skills"]] == ["merchants"]
