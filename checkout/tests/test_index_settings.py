# SPDX-License-Identifier: AGPL-3.0-or-later
"""Which Index 234 talks to: the simulator unless told otherwise, Index's own addresses only, a key for the
tokens, and caps 234 sets under Index's bounds."""

import pytest

from checkout.commerce.index.bounds import limits_for
from checkout.commerce.index.settings import DEFAULT_CAPS_KOBO, REAL_MCP_URL, IndexSettings
from checkout.config import Settings
from checkout.errors import ConfigError
from tests.support import make_stack

KEY = "k" * 40


def settings(**env: str) -> IndexSettings:
    return IndexSettings.from_env(env.get)


class TestTheModeAndTheAddress:
    def test_is_the_simulator_unless_told_otherwise(self):
        assert settings().mode == "simulated" and not settings().live

    def test_live_uses_the_real_address_by_default(self):
        found = settings(INDEX_MODE="live", INDEX_TOKEN_KEY=KEY)
        assert found.live and found.mcp_url == REAL_MCP_URL

    @pytest.mark.parametrize(
        "url",
        [
            "https://index.mcp.paystack.africa/mcp",
            "https://index.paystack.com/mcp",
            "https://index.mcp.paystack.africa:443/mcp/",
        ],
    )
    def test_accepts_an_address_on_indexs_own_hosts(self, url):
        assert settings(INDEX_MODE="live", INDEX_TOKEN_KEY=KEY, INDEX_MCP_URL=url).mcp_url == url.rstrip("/")

    @pytest.mark.parametrize(
        "url",
        [
            "http://index.mcp.paystack.africa/mcp",
            "https://evil.example/mcp",
            "https://index.mcp.paystack.africa.evil.example/mcp",
            "https://user:pw@index.mcp.paystack.africa/mcp",
            "https://index.mcp.paystack.africa:8443/mcp",
            "https://index.mcp.paystack.africa/mcp?x=1",
            "http://localhost:8787/sim/index/mcp",
        ],
    )
    def test_refuses_any_other_address(self, url):
        with pytest.raises(ConfigError, match="INDEX_MCP_URL"):
            settings(INDEX_MODE="live", INDEX_TOKEN_KEY=KEY, INDEX_MCP_URL=url)

    def test_the_simulator_takes_no_address_of_its_own(self):
        with pytest.raises(ConfigError, match="INDEX_MODE=live"):
            settings(INDEX_MCP_URL=REAL_MCP_URL)

    def test_refuses_a_mode_it_does_not_know(self):
        with pytest.raises(ConfigError, match="INDEX_MODE"):
            settings(INDEX_MODE="sandbox")


class TestTheTokenKey:
    def test_live_needs_a_key(self):
        with pytest.raises(ConfigError, match="INDEX_TOKEN_KEY"):
            settings(INDEX_MODE="live")

    def test_a_short_key_is_refused_in_any_mode(self):
        with pytest.raises(ConfigError, match="at least 32"):
            settings(INDEX_TOKEN_KEY="short")

    def test_the_key_is_not_shown_by_the_settings_repr(self):
        assert KEY not in repr(settings(INDEX_MODE="live", INDEX_TOKEN_KEY=KEY))

    def test_the_whole_configuration_reads_it(self):
        env = {"APPROVAL_SECRET": "x-not-real", "INDEX_MODE": "live", "INDEX_TOKEN_KEY": KEY}
        assert Settings.from_env(env.get).index.live


class TestTheCaps:
    def test_default_caps_sit_below_indexs_bounds(self):
        assert limits_for("airtime", IndexSettings()) == (5_000, 500_000)
        assert limits_for("electricity", IndexSettings()) == (100_000, 5_000_000)
        assert limits_for("food", IndexSettings()) == (50_000, 2_000_000)

    def test_a_cap_is_set_by_json_and_never_goes_above_indexs_bound(self):
        raised = settings(INDEX_CAPS_KOBO='{"airtime": 900000, "food": 1000000}')
        assert limits_for("airtime", raised)[1] == 500_000
        assert limits_for("food", raised)[1] == 1_000_000
        assert limits_for("electricity", raised)[1] == DEFAULT_CAPS_KOBO["electricity"]

    @pytest.mark.parametrize("raw", ["not json", "[1]", '{"water": 5}', '{"airtime": 0}', '{"airtime": "9"}'])
    def test_refuses_a_cap_it_cannot_read(self, raw):
        with pytest.raises(ConfigError, match="INDEX_CAPS_KOBO"):
            settings(INDEX_CAPS_KOBO=raw)

    def test_a_cap_below_the_least_leaves_the_least(self):
        assert limits_for("electricity", settings(INDEX_CAPS_KOBO='{"electricity": 5}')) == (100_000, 100_000)


class TestTheWiring:
    def test_live_needs_an_https_chat_host_to_come_back_to(self):
        with pytest.raises(ConfigError, match="HOST_PUBLIC_URL"):
            make_stack(index=IndexSettings("live", REAL_MCP_URL, KEY))

    def test_simulated_returns_to_the_chat_host_when_it_is_known(self):
        stack = make_stack(host_public_url="http://localhost:9601")
        assert (
            stack.app.contexts["merchants"].index.accounts._redirect
            == "http://localhost:9601/connect/index/callback"
        )
