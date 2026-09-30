# SPDX-License-Identifier: AGPL-3.0-or-later
"""The live-check script: it proves itself against the simulators, refuses live keys, prints no secret, and
with keys talks only to the Paystack test API and the VTpass sandbox (here, a scripted stand-in for both)."""

import re

import pytest

from checkout.transport import TransportError
from tests.keys import fake_key
from tests.support import FakeClock, ScriptedTransport, json_reply
from tools.live_check import read_env_file, run

TEST_KEY = fake_key("test", "livecheckdummy123")
VTPASS = {"VTPASS_API_KEY": "api-dummy", "VTPASS_PUBLIC_KEY": "PK_dummy", "VTPASS_SECRET_KEY": "SK_dummy"}


async def run_checked(capsys, argv, env, transport=None):
    code = await run(argv, env, FakeClock(), transport)
    return code, capsys.readouterr().out


async def test_the_self_test_passes_against_the_simulators(capsys):
    code, out = await run_checked(capsys, ["--self-test"], {})
    assert code == 0 and "0 failed" in out
    assert "SELF-TEST" in out and "VTpass accepts the credentials" in out


async def test_a_simulated_starter_business_is_a_note_not_a_failure(capsys):
    code, out = await run_checked(capsys, ["--self-test"], {"SIM_PAYOUTS_REFUSED": "1"})
    assert code == 0 and "payouts unavailable on this account" in out


async def test_a_simulated_vtpass_that_refuses_the_keys_fails_with_the_owners_fix(capsys):
    code, out = await run_checked(capsys, ["--self-test"], {"SIM_VTPASS_REJECT_CREDENTIALS": "1"})
    assert code == 1
    assert "[FAIL] VTpass accepts the credentials" in out and 'API AUTHENTICATION TYPE to "all"' in out
    assert "airtime to the success number" not in out, "the purchase checks are skipped"


async def test_no_keys_checks_nothing_and_says_so(capsys):
    code, out = await run_checked(capsys, [], {})
    assert code == 3 and "Nothing was checked" in out
    assert "skipped: no PAYSTACK_TEST_SECRET_KEY" in out and "skipped: no VTPASS_API_KEY" in out


async def test_a_live_key_is_refused_and_never_printed(capsys):
    live = fake_key("live", "dummydummy123456")
    code, out = await run_checked(capsys, ["--self-test"], {"PAYSTACK_TEST_SECRET_KEY": live})
    assert code == 2 and "live key" in out
    assert "dummydummy" not in out


def scripted_paystack(sent):
    assert sent.url.startswith("https://api.paystack.co/"), f"a call to {sent.url}"
    assert sent.headers["authorization"] == f"Bearer {TEST_KEY}"
    path = sent.url.removeprefix("https://api.paystack.co")
    if path == "/transaction/initialize":
        return json_reply(
            {
                "status": True,
                "data": {
                    "authorization_url": "https://checkout.paystack.com/abc",
                    "access_code": "abc",
                    "reference": sent.body["reference"],
                },
            }
        )
    if path.startswith("/transaction/verify/"):
        return json_reply(
            {
                "status": True,
                "data": {"status": "abandoned", "reference": "r", "amount": 5000, "currency": "NGN"},
            }
        )
    if path.startswith("/bank/resolve"):
        return json_reply({"status": True, "data": {"account_name": "Test"}})
    if path == "/transferrecipient":
        return json_reply(
            {
                "status": True,
                "data": {"recipient_code": "RCP_x", "name": "Test", "details": {"bank_name": "Zenith Bank"}},
            }
        )
    if path == "/transfer":
        return json_reply(
            {"status": False, "message": "You cannot initiate third party payouts as a starter business"}, 400
        )
    return json_reply({"status": False, "message": "not scripted"}, 404)


async def test_with_a_test_key_it_talks_only_to_the_paystack_test_api_and_prints_no_secret(capsys):
    transport = ScriptedTransport(
        lambda sent: scripted_paystack(sent) if "paystack" in sent.url else pytest.fail(sent.url)
    )
    code, out = await run_checked(capsys, [], {"PAYSTACK_TEST_SECRET_KEY": TEST_KEY}, transport)
    assert TEST_KEY not in out and "livecheckdummy" not in out
    assert "Paystack test mode (no real money moves)" in out
    assert "[ok]   initialize a transaction" in out
    assert "payouts unavailable on this account" in out
    assert code == 1, "the repeated reference was 'accepted' by the script's stand-in, which is a failure"
    assert all(call.url.startswith("https://api.paystack.co/") for call in transport.calls)


async def test_no_transfer_skips_the_transfer_checks(capsys):
    transport = ScriptedTransport(scripted_paystack)
    await run_checked(capsys, ["--no-transfer"], {"PAYSTACK_TEST_SECRET_KEY": TEST_KEY}, transport)
    assert not any("/transfer" in call.url or "/bank/" in call.url for call in transport.calls)


async def test_with_vtpass_keys_it_stops_after_a_refused_balance_and_places_no_order(capsys):
    transport = ScriptedTransport(
        lambda sent: json_reply({"a": 1}) if "service-variations" in sent.url
        else json_reply("Invalid Credentials.", 401)
    )  # fmt: skip
    code, out = await run_checked(capsys, [], VTPASS, transport)
    assert code == 1 and "refused this account's credentials (HTTP 401)" in out
    assert not any(call.url.endswith("/pay") for call in transport.calls)
    assert all(call.url.startswith("https://sandbox.vtpass.com/api/") for call in transport.calls)
    assert "SK_dummy" not in out and "api-dummy" not in out


async def test_an_unreachable_vtpass_is_reported_not_raised(capsys):
    transport = ScriptedTransport(lambda sent: TransportError("no route"))
    code, out = await run_checked(capsys, [], VTPASS, transport)
    assert code == 1 and "VTpass could not be reached" in out


def test_an_env_file_is_read_as_plain_lines(tmp_path):
    path = tmp_path / "keys.env"
    path.write_text("# a comment\nVTPASS_API_KEY='abc'\n\nPAYER_EMAIL = me@example.com\nnot a line\n")
    assert read_env_file(path) == {"VTPASS_API_KEY": "abc", "PAYER_EMAIL": "me@example.com"}


def test_the_script_source_holds_no_key_shaped_text():
    from pathlib import Path

    source = (Path(__file__).parents[1] / "tools" / "live_check.py").read_text()
    assert not re.search(r"sk_(?:test|live)_[A-Za-z0-9]{8,}", source)
