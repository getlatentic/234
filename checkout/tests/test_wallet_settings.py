# SPDX-License-Identifier: AGPL-3.0-or-later
"""The wallet's settings (wallet/settings.py): the caps 234 sets."""

import pytest

from checkout.config import Settings
from checkout.errors import ConfigError
from checkout.wallet.settings import WalletSettings


def load(**env: str) -> WalletSettings:
    return Settings.from_env({"APPROVAL_SECRET": "x-not-real", **env}.get).wallet


def test_defaults_are_the_caps_of_the_design():
    assert load() == WalletSettings(20_000_000, 5_000_000, 10_000_000)


def test_reads_the_caps():
    wallet = load(
        WALLET_BALANCE_CAP_KOBO="5000000",
        WALLET_WITHDRAWAL_KOBO="100000",
        WALLET_WITHDRAWALS_DAILY_KOBO="200000",
    )
    assert wallet == WalletSettings(5_000_000, 100_000, 200_000)


@pytest.mark.parametrize("raw", ["0", "-1", "1.5", "lots"])
def test_a_cap_is_a_positive_whole_number_of_kobo(raw):
    with pytest.raises(ConfigError, match="WALLET_BALANCE_CAP_KOBO"):
        load(WALLET_BALANCE_CAP_KOBO=raw)


def test_one_withdrawal_cannot_be_more_than_a_days_withdrawals():
    with pytest.raises(ConfigError, match="WALLET_WITHDRAWAL_KOBO cannot be more"):
        load(WALLET_WITHDRAWAL_KOBO="300000", WALLET_WITHDRAWALS_DAILY_KOBO="200000")
