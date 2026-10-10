# SPDX-License-Identifier: AGPL-3.0-or-later
"""The caps 234 sets on what a person's wallet may hold and take out (docs/wallet.md, "Safety limits"). Which
Bachs a top-up is paid on is bachs/settings.py's."""

from collections.abc import Callable
from dataclasses import dataclass

from ..errors import ConfigError
from ..money import Kobo


@dataclass(frozen=True)
class WalletSettings:
    balance_cap_kobo: Kobo = 20_000_000
    withdrawal_kobo: Kobo = 5_000_000
    withdrawals_daily_kobo: Kobo = 10_000_000

    @classmethod
    def from_env(cls, read: Callable[[str], str | None]) -> WalletSettings:
        base = cls()
        settings = cls(
            balance_cap_kobo=_positive(read, "WALLET_BALANCE_CAP_KOBO", base.balance_cap_kobo),
            withdrawal_kobo=_positive(read, "WALLET_WITHDRAWAL_KOBO", base.withdrawal_kobo),
            withdrawals_daily_kobo=_positive(
                read, "WALLET_WITHDRAWALS_DAILY_KOBO", base.withdrawals_daily_kobo
            ),
        )
        if settings.withdrawal_kobo > settings.withdrawals_daily_kobo:
            raise ConfigError("WALLET_WITHDRAWAL_KOBO cannot be more than WALLET_WITHDRAWALS_DAILY_KOBO.")
        return settings


def _positive(read: Callable[[str], str | None], name: str, fallback: int) -> int:
    raw = (read(name) or "").strip()
    if not raw:
        return fallback
    if not raw.isdecimal() or int(raw) <= 0:
        raise ConfigError(f'{name} must be a positive whole number of kobo, got "{raw}".')
    return int(raw)
