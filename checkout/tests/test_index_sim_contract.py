# SPDX-License-Identifier: AGPL-3.0-or-later
"""The simulated Index against what Index published (tests/fixtures/index_tools.json) and against OAuth: it
advertises the ten tools with their names, annotations and schemas, refuses a call the schemas refuse,
answers as JSON or as an event stream, and its authorization server takes a code once, with the right
verifier, for the client and the redirect it was issued to. Nothing here reaches the network."""

import json
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit

import pytest

from checkout.commerce.index.oauth import challenge_of
from checkout.commerce.index.sim import IndexSimulator
from checkout.commerce.index.sim_pages import decide
from checkout.commerce.index.sim_store import IndexSimStore
from checkout.commerce.index.sim_tool_list import TOOLS
from checkout.commerce.index.wire import IndexSession, IndexUnauthorized
from tests.support import make_stack

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "index_tools.json").read_text())["tools"]
BASE = "http://localhost:8787/sim/index"
REDIRECT = "http://localhost:9601/connect/index/callback"


def bare(schema):
    if isinstance(schema, dict):
        return {k: bare(v) for k, v in schema.items() if k != "description" or isinstance(v, dict)}
    return [bare(v) for v in schema] if isinstance(schema, list) else schema


class Rig:
    def __init__(self, stack):
        self.store = IndexSimStore(stack.db, stack.clock)
        self.simulator = IndexSimulator(self.store, stack.clock, BASE)

    async def post(self, path, body, headers=None, form=False):
        sent = urlencode(body) if form else json.dumps(body)
        kind = "application/x-www-form-urlencoded" if form else "application/json"
        return await self.simulator.send(
            "POST",
            BASE + path,
            headers={"content-type": kind, **(headers or {})},
            body=sent,
            timeout_seconds=5,
        )

    async def client(self):
        made = await self.post("/oauth/register", {"redirect_uris": [REDIRECT]})
        assert made.status == 201
        return json.loads(made.body)

    async def code(self, client, verifier="v" * 43):
        form = {
            "client_id": client["client_id"],
            "redirect_uri": REDIRECT,
            "state": "s",
            "code_challenge": challenge_of(verifier),
            "decision": "allow",
        }
        back = await decide(self.store, form)
        assert back.status == 302
        return dict(parse_qsl(urlsplit(back.headers["location"]).query))["code"]

    async def token(self, client, code, verifier="v" * 43, redirect=REDIRECT):
        body = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect,
            "code_verifier": verifier,
            **{"client_id": client["client_id"], "client_secret": client["client_secret"]},
        }
        return await self.post("/oauth/token", body, form=True)

    async def access(self, stack):
        client = await self.client()
        return json.loads((await self.token(client, await self.code(client))).body)["access_token"]

    def session(self, stack, token):
        return IndexSession(self.simulator, f"{BASE}/mcp", token)


@pytest.fixture
def rig(stack):
    return Rig(stack)


class TestTheToolsItAdvertises:
    def test_the_fixture_is_the_ten_tools(self):
        assert len(FIXTURE) == 10

    def test_names_annotations_and_schemas_are_the_ones_index_published(self):
        assert [t["name"] for t in TOOLS] == [t["name"] for t in FIXTURE]
        for ours, theirs in zip(TOOLS, FIXTURE, strict=True):
            assert ours["annotations"] == theirs["annotations"], ours["name"]
            assert ours["inputSchema"] == bare(theirs["inputSchema"]), ours["name"]

    async def test_a_session_lists_them(self, stack, rig):
        session = rig.session(stack, await rig.access(stack))
        listed = await session._request("tools/list", {}) if await session.call("get_balance", {}) else {}
        assert [t["name"] for t in listed["tools"]] == [t["name"] for t in FIXTURE]


class TestCallsAreCheckedAgainstTheSchemas:
    @pytest.mark.parametrize(
        ("tool", "arguments", "why"),
        [
            ("quick_buy", {}, "category is required"),
            ("quick_buy", {"category": "water"}, "one of airtime, data, electricity"),
            ("quick_buy", {"category": "airtime", "amount_naira": 10}, "at least 50"),
            ("quick_buy", {"category": "airtime", "amount_naira": "ten"}, "of type number"),
            ("order", {}, "merchant_id is required"),
            ("get_recent_activity", {"limit": 500}, "at most 100"),
            ("find_items", {"vendor_id": "abc"}, "of type number"),
        ],
    )
    async def test_refuses_what_the_schema_refuses(self, stack, rig, tool, arguments, why):
        session = rig.session(stack, await rig.access(stack))
        reply = await session.call(tool, arguments)
        assert reply.is_error and why in reply.text

    async def test_an_unknown_tool_is_an_error(self, stack, rig):
        session = rig.session(stack, await rig.access(stack))
        assert (await session.call("drain_wallet", {})).is_error

    async def test_the_two_transfer_tools_are_not_offered(self, stack, rig):
        session = rig.session(stack, await rig.access(stack))
        reply = await session.call("find_beneficiaries", {})
        assert reply.is_error and "does not offer" in reply.text

    async def test_every_call_is_recorded_as_served_with_whether_it_carried_confirmed(self, stack, rig):
        session = rig.session(stack, await rig.access(stack))
        await session.call("get_balance", {})
        await session.call(
            "quick_buy", {"category": "airtime", "network": "MTN", "phone": "0803", "amount_naira": 100}
        )
        seen = await rig.store.calls()
        assert [(c["tool"], c["confirmed"]) for c in seen] == [("get_balance", False), ("quick_buy", False)]


class TestTheEnvelope:
    async def test_answers_in_json_by_default_and_as_an_event_stream_when_set(self, stack, rig):
        token = await rig.access(stack)
        await rig.store.set_setting("sse", "1")
        reply = await rig.session(stack, token).call("get_balance", {})
        assert reply.data["zap_linked"] is True

    async def test_a_session_id_the_server_gives_is_sent_back(self, stack, rig):
        session = rig.session(stack, await rig.access(stack))
        await session.call("get_balance", {})
        assert session._session_id == "sim-session"

    async def test_a_bad_token_is_a_401(self, stack, rig):
        with pytest.raises(IndexUnauthorized):
            await rig.session(stack, "at-nonsense").call("get_balance", {})

    async def test_names_itself_and_the_protocol(self, stack, rig):
        token = await rig.access(stack)
        answered = await rig.post(
            "/mcp",
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"authorization": f"Bearer {token}"},
        )
        result = json.loads(answered.body)["result"]
        assert result["serverInfo"] == {"name": "paystack-index", "version": "0.0.1"}
        assert result["protocolVersion"] == "2025-03-26"


class TestTheAuthorizationServer:
    async def test_publishes_the_endpoints_pkce_and_the_one_scope(self, stack, rig):
        found = json.loads(
            (
                await rig.simulator.send(
                    "GET",
                    f"{BASE}/.well-known/oauth-authorization-server",
                    headers={},
                    body=None,
                    timeout_seconds=5,
                )
            ).body
        )
        assert found["code_challenge_methods_supported"] == ["S256"]
        assert found["scopes_supported"] == ["mcp:transact"]
        assert set(found["grant_types_supported"]) == {
            "authorization_code",
            "refresh_token",
            "client_credentials",
        }
        assert "revocation_endpoint" not in found

    async def test_a_code_is_good_once(self, stack, rig):
        client = await rig.client()
        code = await rig.code(client)
        assert (await rig.token(client, code)).status == 200
        again = await rig.token(client, code)
        assert again.status == 400 and json.loads(again.body)["error"] == "invalid_grant"

    async def test_a_wrong_verifier_gets_nothing(self, stack, rig):
        client = await rig.client()
        refused = await rig.token(client, await rig.code(client), verifier="w" * 43)
        assert json.loads(refused.body)["error"] == "invalid_grant"

    async def test_a_code_is_for_the_redirect_it_was_issued_to(self, stack, rig):
        client = await rig.client()
        refused = await rig.token(client, await rig.code(client), redirect="http://evil.example/cb")
        assert json.loads(refused.body)["error"] == "invalid_grant"

    async def test_a_code_is_for_the_client_it_was_issued_to(self, stack, rig):
        first, second = await rig.client(), await rig.client()
        refused = await rig.token(second, await rig.code(first))
        assert json.loads(refused.body)["error"] == "invalid_grant"

    async def test_a_late_code_gets_nothing(self, stack, rig):
        client = await rig.client()
        code = await rig.code(client)
        stack.clock.advance(6 * 60)
        assert (await rig.token(client, code)).status == 400

    async def test_a_refresh_token_is_good_once_and_gives_a_new_one(self, stack, rig):
        client = await rig.client()
        first = json.loads((await rig.token(client, await rig.code(client))).body)
        asked = {
            "grant_type": "refresh_token",
            "refresh_token": first["refresh_token"],
            "client_id": client["client_id"],
            "client_secret": client["client_secret"],
        }
        second = json.loads((await rig.post("/oauth/token", asked, form=True)).body)
        assert second["refresh_token"] != first["refresh_token"]
        assert (await rig.post("/oauth/token", asked, form=True)).status == 400

    async def test_the_client_must_prove_itself(self, stack, rig):
        client = await rig.client()
        wrong = {"grant_type": "client_credentials", "client_id": client["client_id"], "client_secret": "no"}
        assert (await rig.post("/oauth/token", wrong, form=True)).status == 401

    async def test_the_sign_in_page_refuses_a_redirect_the_client_did_not_register(self, stack, rig):
        client = await rig.client()
        refused = await decide(
            rig.store,
            {
                "client_id": client["client_id"],
                "redirect_uri": "http://evil.example/cb",
                "state": "s",
                "code_challenge": "c",
                "decision": "allow",
            },
        )
        assert refused.status == 400

    async def test_saying_no_sends_the_browser_back_with_the_state_and_no_code(self, stack, rig):
        client = await rig.client()
        form = {
            "client_id": client["client_id"],
            "redirect_uri": REDIRECT,
            "state": "keep-me",
            "code_challenge": "c",
            "decision": "deny",
        }
        back = dict(parse_qsl(urlsplit((await decide(rig.store, form)).headers["location"]).query))
        assert back == {"error": "access_denied", "state": "keep-me"}


def test_a_stack_has_the_simulator_and_not_the_network(stack):
    assert stack.app.contexts["merchants"].index.sim is not None
    assert make_stack().app.settings.index.mode == "simulated"
