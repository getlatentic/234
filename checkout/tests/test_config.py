# SPDX-License-Identifier: AGPL-3.0-or-later
"""Configuration rules, ported from the TypeScript demo's config.test.ts. The keys are fakes."""

import pytest

from checkout.config import Settings
from checkout.errors import ConfigError
from tests.keys import fake_key, fake_public_key

TEST_KEY = fake_key("test")
LIVE_KEY = fake_key("live")


def load(**env: str) -> Settings:
    return Settings.from_env({"APPROVAL_SECRET": "x-not-real", **env}.get)


class TestPaystackMode:
    def test_is_simulated_when_no_key_is_set(self):
        paystack = load().paystack
        assert (paystack.mode, paystack.secret_key, dict(paystack.overrides)) == ("simulated", None, {})

    def test_is_test_mode_when_a_test_key_is_set(self):
        paystack = load(PAYSTACK_TEST_SECRET_KEY=TEST_KEY).paystack
        assert (paystack.mode, paystack.secret_key) == ("test", TEST_KEY)

    def test_stays_simulated_on_request_and_does_not_carry_the_key(self):
        paystack = load(PAYSTACK_TEST_SECRET_KEY=TEST_KEY, PAYSTACK_MODE="simulated").paystack
        assert (paystack.mode, paystack.secret_key) == ("simulated", None)

    def test_a_live_key_is_refused_at_startup(self):
        with pytest.raises(ConfigError, match="live key"):
            load(PAYSTACK_TEST_SECRET_KEY=LIVE_KEY)

    def test_a_live_key_under_the_plain_name_is_refused_too(self):
        with pytest.raises(ConfigError, match="PAYSTACK_SECRET_KEY is a live key"):
            load(PAYSTACK_SECRET_KEY=LIVE_KEY)

    def test_the_plain_name_is_not_used_even_when_it_holds_a_test_key(self):
        assert load(PAYSTACK_SECRET_KEY=TEST_KEY).paystack.mode == "simulated"

    @pytest.mark.parametrize("mode", ["simulated", "test"])
    def test_a_live_key_is_refused_whatever_mode_is_requested(self, mode):
        with pytest.raises(ConfigError, match="live key"):
            load(PAYSTACK_TEST_SECRET_KEY=LIVE_KEY, PAYSTACK_MODE=mode)

    def test_the_error_never_repeats_the_key(self):
        with pytest.raises(ConfigError) as refused:
            load(PAYSTACK_TEST_SECRET_KEY=LIVE_KEY)
        assert "abcdefgh12345678" not in str(refused.value)

    @pytest.mark.parametrize("key", [fake_public_key(), "abc", "sk_test_"])
    def test_a_value_that_is_not_a_test_secret_key_is_refused(self, key):
        with pytest.raises(ConfigError, match="sk_test_"):
            load(PAYSTACK_TEST_SECRET_KEY=key)

    def test_test_mode_without_a_key_is_refused(self):
        with pytest.raises(ConfigError, match="needs PAYSTACK_TEST_SECRET_KEY"):
            load(PAYSTACK_MODE="test")

    def test_an_unknown_mode_is_refused(self):
        with pytest.raises(ConfigError, match='"simulated" or "test"'):
            load(PAYSTACK_MODE="live")


class TestPerConnectorModes:
    def test_one_connector_simulates_while_the_rest_use_the_real_test_account(self):
        paystack = load(PAYSTACK_TEST_SECRET_KEY=TEST_KEY, SEND_MONEY_MODE="simulated").paystack
        assert paystack.mode_for("send-money") == "simulated"
        assert paystack.mode_for("paystack-pay") == "test"
        assert paystack.mode_for("airtime") == "test"
        assert paystack.secret_key == TEST_KEY

    def test_one_connector_is_real_while_the_default_is_simulated(self):
        paystack = load(
            PAYSTACK_TEST_SECRET_KEY=TEST_KEY, PAYSTACK_MODE="simulated", PAYSTACK_PAY_MODE="real"
        ).paystack
        assert paystack.mode_for("paystack-pay") == "test"
        assert paystack.mode_for("send-money") == "simulated"
        assert paystack.secret_key == TEST_KEY

    def test_every_connectors_own_variable_is_read(self):
        paystack = load(
            PAYSTACK_TEST_SECRET_KEY=TEST_KEY,
            PAYSTACK_MODE="simulated",
            AIRTIME_MODE="real",
            FOOD_ORDER_MODE="real",
        ).paystack
        assert dict(paystack.overrides) == {"airtime": "test", "food-order": "test"}

    def test_the_key_is_not_carried_when_every_connector_is_simulated(self):
        paystack = load(
            PAYSTACK_TEST_SECRET_KEY=TEST_KEY, PAYSTACK_MODE="simulated", SEND_MONEY_MODE="simulated"
        ).paystack
        assert paystack.secret_key is None

    def test_real_mode_for_a_connector_without_a_key_is_refused(self):
        with pytest.raises(ConfigError, match="needs PAYSTACK_TEST_SECRET_KEY"):
            load(SEND_MONEY_MODE="real")

    def test_an_unknown_value_is_refused(self):
        with pytest.raises(ConfigError, match='"simulated" or "real"'):
            load(PAYSTACK_TEST_SECRET_KEY=TEST_KEY, SEND_MONEY_MODE="live")

    def test_a_live_key_is_refused_whatever_the_connector_modes_say(self):
        with pytest.raises(ConfigError, match="live key"):
            load(PAYSTACK_TEST_SECRET_KEY=LIVE_KEY, SEND_MONEY_MODE="simulated")


VTPASS_CREDENTIALS = {
    "VTPASS_API_KEY": "api",
    "VTPASS_PUBLIC_KEY": "PK_public",
    "VTPASS_SECRET_KEY": "SK_secret",
}


class TestVtpassMode:
    def test_is_simulated_without_credentials(self):
        vtpass = load().vtpass
        assert (vtpass.mode, vtpass.credentials, vtpass.debug) == ("simulated", None, False)

    def test_is_sandbox_with_all_three_credentials(self):
        assert load(**VTPASS_CREDENTIALS).vtpass.mode == "sandbox"

    def test_sandbox_with_partial_credentials_is_refused(self):
        with pytest.raises(ConfigError, match="VTPASS_API_KEY, VTPASS_PUBLIC_KEY and VTPASS_SECRET_KEY"):
            load(VTPASS_MODE="sandbox", VTPASS_API_KEY="api")

    @pytest.mark.parametrize("credentials", [{}, VTPASS_CREDENTIALS])
    def test_live_mode_is_refused_with_or_without_keys(self, credentials):
        with pytest.raises(ConfigError, match="VTPASS_MODE=live is refused"):
            load(VTPASS_MODE="live", **credentials)

    def test_credentials_are_not_carried_in_simulated_mode(self):
        assert load(**VTPASS_CREDENTIALS, VTPASS_MODE="simulated").vtpass.credentials is None


class TestLimitsAndTiming:
    def test_defaults_are_50000_per_payment_and_100000_a_day(self):
        settings = load()
        assert (settings.per_payment_limit_kobo, settings.daily_limit_kobo) == (5_000_000, 10_000_000)

    def test_limits_are_read(self):
        settings = load(PER_PAYMENT_LIMIT_KOBO="200000", DAILY_LIMIT_KOBO="500000")
        assert (settings.per_payment_limit_kobo, settings.daily_limit_kobo) == (200_000, 500_000)

    @pytest.mark.parametrize("value", ["0", "-5", "abc", "1.5"])
    def test_a_limit_that_is_not_a_positive_whole_number_is_refused(self, value):
        with pytest.raises(ConfigError, match="positive whole number"):
            load(PER_PAYMENT_LIMIT_KOBO=value)

    def test_a_per_payment_limit_above_the_daily_limit_is_refused(self):
        with pytest.raises(ConfigError, match="cannot be more than"):
            load(PER_PAYMENT_LIMIT_KOBO="900000", DAILY_LIMIT_KOBO="500000")

    def test_simulator_switches_are_read(self):
        sim = load(SIM_TRANSFER_OTP="true", SIM_PENDING_SECONDS="3").simulator
        assert (sim.transfer_otp, sim.pending_seconds) == (True, 3)
        with pytest.raises(ConfigError, match="true or false"):
            load(SIM_TRANSFER_OTP="maybe")

    def test_the_approval_secret_is_required(self):
        with pytest.raises(ConfigError, match="APPROVAL_SECRET"):
            Settings.from_env({}.get)


def test_a_settings_object_never_shows_a_secret_when_printed():
    settings = load(PAYSTACK_TEST_SECRET_KEY=TEST_KEY, VTPASS_API_KEY="api-shh", VTPASS_PUBLIC_KEY="PK_shh",
                    VTPASS_SECRET_KEY="SK_shh")  # fmt: skip
    text = repr(settings)
    for secret in (TEST_KEY, "api-shh", "PK_shh", "SK_shh", "x-not-real"):
        assert secret not in text
