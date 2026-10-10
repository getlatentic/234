# SPDX-License-Identifier: AGPL-3.0-or-later
"""Bachs' webhook signature (bachs/signature.py) and the hook that requires it (provider_hooks/bachs.py):
HMAC-SHA256 over `{t}.{raw body}`, any one `v1` matching, nothing older than five minutes or dated ahead of
this clock, and a refused delivery credits nothing."""

import hashlib
import hmac

import pytest

from checkout.bachs.signature import (
    FUTURE_SKEW_SECONDS,
    SIGNATURE_HEADER,
    TOLERANCE_SECONDS,
    Verdict,
    check,
    header_for,
    parse,
    sign,
)
from checkout.http import handle
from tests.support import make_stack
from tests.topup_support import SECRET, SIMULATED, audited, balance, deliver, funds, started, succeeded

BODY = b'{"type":"collection.succeeded","data":{}}'
NOW_MS = 1_790_676_000_000
NOW = NOW_MS // 1000


def test_the_signature_is_hmac_sha256_hex_over_the_timestamp_dot_the_raw_body():
    expected = hmac.new(b"whsec_x", f"{NOW}.".encode() + BODY, hashlib.sha256).hexdigest()
    assert sign("whsec_x", NOW, BODY) == expected
    assert header_for(("whsec_x",), NOW, BODY) == f"t={NOW},v1={expected}"


def test_the_header_gives_its_timestamp_and_every_v1():
    assert parse("t=12, v1=aa,v0=zz,v1=bb") == (12, ["aa", "bb"])
    assert parse("v1=aa") == (None, ["aa"])
    assert parse("t=-5,v1=aa") == (None, ["aa"])
    assert parse("t=١٢,v1=aa") == (None, ["aa"])


def test_a_valid_signature_is_genuine():
    assert check(BODY, header_for(("s1",), NOW, BODY), ("s1",), NOW_MS) is Verdict.GENUINE


@pytest.mark.parametrize(
    "header",
    [
        "",
        f"t={NOW}",
        f"v1={sign('s1', NOW, BODY)}",
        f"t={NOW},v1={sign('another secret', NOW, BODY)}",
        f"t={NOW},v1={sign('s1', NOW, BODY + b' ')}",
        f"t={NOW + 1},v1={sign('s1', NOW, BODY)}",
        f"t={NOW},v1={sign('s1', NOW, BODY).upper()}",
        f"t={NOW},v1=ünïcode",
    ],
)
def test_a_forged_or_altered_signature_is_refused(header):
    assert check(BODY, header, ("s1",), NOW_MS) is Verdict.UNSIGNED


def test_while_a_secret_is_rotated_either_v1_is_enough():
    both = header_for(("old", "new"), NOW, BODY)
    assert check(BODY, both, ("new",), NOW_MS) is Verdict.GENUINE
    assert check(BODY, both, ("old",), NOW_MS) is Verdict.GENUINE
    assert check(BODY, header_for(("new",), NOW, BODY), ("old", "new"), NOW_MS) is Verdict.GENUINE
    assert check(BODY, header_for(("older",), NOW, BODY), ("old", "new"), NOW_MS) is Verdict.UNSIGNED


def test_no_secret_verifies_nothing():
    assert check(BODY, header_for(("s1",), NOW, BODY), (), NOW_MS) is Verdict.UNSIGNED


def test_a_delivery_older_than_five_minutes_is_stale():
    at_limit = header_for(("s1",), NOW - TOLERANCE_SECONDS, BODY)
    past_it = header_for(("s1",), NOW - TOLERANCE_SECONDS - 1, BODY)
    assert check(BODY, at_limit, ("s1",), NOW_MS) is Verdict.GENUINE
    assert check(BODY, past_it, ("s1",), NOW_MS) is Verdict.STALE


def test_a_delivery_dated_ahead_beyond_the_skew_is_refused():
    within = header_for(("s1",), NOW + FUTURE_SKEW_SECONDS, BODY)
    beyond = header_for(("s1",), NOW + FUTURE_SKEW_SECONDS + 1, BODY)
    assert check(BODY, within, ("s1",), NOW_MS) is Verdict.GENUINE
    assert check(BODY, beyond, ("s1",), NOW_MS) is Verdict.FUTURE


class TestTheHook:
    async def test_a_genuine_delivery_credits(self):
        stack = make_stack(approval_secret=SECRET)
        topup = await started(stack)
        assert (await deliver(stack, succeeded(topup))).status == 200
        assert await balance(stack) == 500_000

    @pytest.mark.parametrize(
        ("secrets", "offset", "reason"),
        [
            (("not the secret",), 0, "unsigned"),
            ((SIMULATED,), -TOLERANCE_SECONDS - 1, "stale"),
            ((SIMULATED,), FUTURE_SKEW_SECONDS + 60, "future"),
        ],
    )
    async def test_a_refused_delivery_is_answered_400_audited_and_credits_nothing(
        self, secrets, offset, reason
    ):
        stack = make_stack(approval_secret=SECRET)
        topup = await started(stack)
        answer = await deliver(stack, succeeded(topup), secrets, stack.clock.now() // 1000 + offset)
        assert answer.status == 400
        assert await funds(stack) == [] and await balance(stack) == 0
        assert [line["reason"] for line in audited(stack, "bachs.webhook.refused")] == [reason]

    async def test_an_unsigned_delivery_credits_nothing(self):
        stack = make_stack(approval_secret=SECRET)
        topup = await started(stack)
        assert (await handle(stack.app, "POST", "/hooks/bachs", {}, succeeded(topup))).status == 400
        assert await funds(stack) == []

    async def test_the_signature_covers_the_body_as_sent(self):
        stack = make_stack(approval_secret=SECRET)
        topup = await started(stack)
        body = succeeded(topup)
        header = header_for((SIMULATED,), stack.clock.now() // 1000, body)
        altered = body.replace(b'"5000.00"', b'"50000.00"')
        answer = await handle(stack.app, "POST", "/hooks/bachs", {SIGNATURE_HEADER: header}, altered)
        assert answer.status == 400 and await funds(stack) == []

    async def test_an_oversized_body_is_refused_unread(self):
        stack = make_stack(approval_secret=SECRET)
        big = b"{" + b" " * (64 * 1024) + b"}"
        assert (await deliver(stack, big)).status == 413
