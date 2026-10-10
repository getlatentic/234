# SPDX-License-Identifier: AGPL-3.0-or-later
"""Which Bachs the wallet's top-ups use (`BACHS_MODE`): the simulator, or the Bachs sandbox with its key and
the webhook endpoint's signing secret (`BACHS_SECRET_KEY`, `BACHS_WEBHOOK_SECRET`, Worker secrets). Live is
refused whatever else is set, and so is a live key in any mode."""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal, cast

from ..errors import ConfigError
from .api import LIVE_KEY_PREFIX, SANDBOX_API_URL

BachsMode = Literal["simulated", "sandbox"]
MODES = ("simulated", "sandbox", "live")
MIN_WEBHOOK_SECRET_LENGTH = 16

_SANDBOX_KEY = re.compile(r"sk_sandbox_[A-Za-z0-9_]{8,}")


@dataclass(frozen=True)
class BachsSettings:
    mode: BachsMode = "simulated"
    secret_key: str | None = field(default=None, repr=False)
    webhook_secret: str | None = field(default=None, repr=False)
    api_url: str = SANDBOX_API_URL

    @classmethod
    def from_env(cls, read: Callable[[str], str | None]) -> BachsSettings:
        mode = _mode(read)
        key = _key(read)
        if mode == "simulated":
            return cls()
        secret = (read("BACHS_WEBHOOK_SECRET") or "").strip()
        if key is None:
            raise ConfigError("BACHS_MODE=sandbox needs BACHS_SECRET_KEY set to a Bachs sandbox key.")
        if len(secret) < MIN_WEBHOOK_SECRET_LENGTH:
            raise ConfigError(
                "BACHS_MODE=sandbox needs BACHS_WEBHOOK_SECRET, the signing secret of the webhook endpoint."
            )
        return cls("sandbox", key, secret)


def _mode(read: Callable[[str], str | None]) -> BachsMode:
    raw = (read("BACHS_MODE") or "simulated").strip().lower()
    if raw not in MODES:
        raise ConfigError(f'BACHS_MODE must be one of {", ".join(MODES)}, got "{raw}".')
    if raw == "live":
        raise ConfigError(
            "BACHS_MODE=live is refused: holding people's balances waits on the licence question in "
            "docs/wallet.md, and this build talks only to the Bachs sandbox and its simulator."
        )
    return cast(BachsMode, raw)


def _key(read: Callable[[str], str | None]) -> str | None:
    key = (read("BACHS_SECRET_KEY") or "").strip() or None
    if key is None:
        return None
    if key.startswith(LIVE_KEY_PREFIX):
        raise ConfigError("BACHS_SECRET_KEY is a live key (sk_live_...). Only a sandbox key is accepted.")
    if not _SANDBOX_KEY.fullmatch(key):
        raise ConfigError("BACHS_SECRET_KEY must be a Bachs sandbox secret key that starts with sk_sandbox_.")
    return key
