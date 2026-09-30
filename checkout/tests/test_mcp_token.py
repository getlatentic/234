# SPDX-License-Identifier: AGPL-3.0-or-later
"""The bearer token that keeps a public Worker's tools to the host that holds it."""

import json

import pytest

from checkout.config import Settings
from checkout.errors import ConfigError
from checkout.http import handle
from tests.support import make_stack

TOKEN = "t" * 40
LIST_TOOLS = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode()


def load(**env: str) -> Settings:
    return Settings.from_env({"APPROVAL_SECRET": "x-not-real", **env}.get)


def stack_with_token():
    return make_stack(mcp_token=TOKEN)


async def call(stack, authorization: str | None, path: str = "/paystack-pay/mcp", method: str = "POST"):
    headers = {} if authorization is None else {"authorization": authorization}
    return await handle(stack.app, method, path, headers, LIST_TOOLS)


class TestTheGate:
    @pytest.mark.parametrize(
        "authorization", [None, "", "Bearer", "Bearer wrong", f"Basic {TOKEN}", TOKEN[:-1]]
    )
    async def test_a_call_without_the_token_is_refused_before_anything_is_read(self, authorization):
        reply = await call(stack_with_token(), authorization)
        assert reply.status == 401
        assert reply.headers["www-authenticate"] == "Bearer"
        assert "tools" not in reply.body

    async def test_the_token_lets_the_call_through(self):
        reply = await call(stack_with_token(), f"Bearer {TOKEN}")
        assert reply.status == 200
        assert json.loads(reply.body)["result"]["tools"]

    async def test_every_connector_is_behind_it_and_an_unknown_one_is_not_revealed(self):
        stack = stack_with_token()
        for connector in ("paystack-pay", "send-money", "airtime", "food-order", "nothing-here"):
            assert (await call(stack, None, f"/{connector}/mcp")).status == 401

    async def test_the_health_check_and_the_checkout_page_stay_public(self):
        stack = stack_with_token()
        assert (await handle(stack.app, "GET", "/health", {}, b"")).status == 200
        assert (await handle(stack.app, "GET", "/sim/checkout/none", {}, b"")).status == 404

    async def test_without_a_configured_token_the_endpoint_is_open_for_local_use(self):
        reply = await handle(make_stack().app, "POST", "/paystack-pay/mcp", {}, LIST_TOOLS)
        assert reply.status == 200


class TestTheSetting:
    def test_a_token_is_read_and_kept_out_of_the_repr(self):
        settings = load(MCP_ACCESS_TOKEN=TOKEN)
        assert settings.mcp_token == TOKEN
        assert TOKEN not in repr(settings)

    def test_no_token_means_none(self):
        assert load().mcp_token is None

    def test_a_short_token_is_refused_and_not_echoed(self):
        with pytest.raises(ConfigError, match="at least 32") as refused:
            load(MCP_ACCESS_TOKEN="short")
        assert "short" not in refused.value.message.replace("at least", "")

    def test_a_deployment_that_requires_a_token_does_not_start_without_one(self):
        with pytest.raises(ConfigError, match="REQUIRE_MCP_TOKEN"):
            load(REQUIRE_MCP_TOKEN="1")

    def test_a_required_token_that_is_present_starts(self):
        assert load(REQUIRE_MCP_TOKEN="1", MCP_ACCESS_TOKEN=TOKEN).mcp_token == TOKEN
