# SPDX-License-Identifier: AGPL-3.0-or-later
"""Which Bachs the top-ups use (bachs/settings.py): simulated by default, the sandbox with a sandbox key and
the endpoint's signing secret, and never live."""

import pytest

from checkout.bachs.settings import BachsSettings
from checkout.config import Settings
from checkout.errors import ConfigError
from tests.topup_support import SANDBOX_KEY, WEBHOOK_SECRET

LIVE_KEY = "sk_" + "live_a1b2c3d4e5f6"


def load(**env: str) -> BachsSettings:
    return Settings.from_env({"APPROVAL_SECRET": "x-not-real", **env}.get).bachs


def test_simulated_by_default():
    assert load() == BachsSettings()


def test_sandbox_reads_the_key_and_the_webhook_secret():
    found = load(BACHS_MODE="Sandbox", BACHS_SECRET_KEY=SANDBOX_KEY, BACHS_WEBHOOK_SECRET=WEBHOOK_SECRET)
    assert found == BachsSettings("sandbox", SANDBOX_KEY, WEBHOOK_SECRET)
    assert SANDBOX_KEY not in repr(found) and WEBHOOK_SECRET not in repr(found)


def test_live_refuses_to_start():
    with pytest.raises(ConfigError, match="BACHS_MODE=live is refused"):
        load(BACHS_MODE="live", BACHS_SECRET_KEY=SANDBOX_KEY, BACHS_WEBHOOK_SECRET=WEBHOOK_SECRET)


def test_an_unknown_mode_refuses_to_start():
    with pytest.raises(ConfigError, match="BACHS_MODE must be one of"):
        load(BACHS_MODE="real")


@pytest.mark.parametrize("mode", ["sandbox", "simulated"])
def test_a_live_key_is_refused_in_any_mode_and_never_echoed(mode):
    with pytest.raises(ConfigError, match="live key") as refused:
        load(BACHS_MODE=mode, BACHS_SECRET_KEY=LIVE_KEY, BACHS_WEBHOOK_SECRET=WEBHOOK_SECRET)
    assert LIVE_KEY not in str(refused.value)


@pytest.mark.parametrize("key", ["sk_" + "test_a1b2c3d4e5f6", "sk_" + "sandbox_short", "a1b2c3d4e5f6a1b2"])
def test_a_key_that_is_not_a_sandbox_key_is_refused(key):
    with pytest.raises(ConfigError, match="starts with sk_sandbox_") as refused:
        load(BACHS_MODE="sandbox", BACHS_SECRET_KEY=key, BACHS_WEBHOOK_SECRET=WEBHOOK_SECRET)
    assert key not in str(refused.value)


def test_sandbox_needs_the_key():
    with pytest.raises(ConfigError, match="needs BACHS_SECRET_KEY"):
        load(BACHS_MODE="sandbox", BACHS_WEBHOOK_SECRET=WEBHOOK_SECRET)


@pytest.mark.parametrize("secret", ["", "short"])
def test_sandbox_needs_the_webhook_secret(secret):
    with pytest.raises(ConfigError, match="needs BACHS_WEBHOOK_SECRET"):
        load(BACHS_MODE="sandbox", BACHS_SECRET_KEY=SANDBOX_KEY, BACHS_WEBHOOK_SECRET=secret)


def test_simulated_mode_holds_no_key():
    assert load(BACHS_SECRET_KEY=SANDBOX_KEY, BACHS_WEBHOOK_SECRET=WEBHOOK_SECRET) == BachsSettings()
