# SPDX-License-Identifier: AGPL-3.0-or-later
"""Who has a wallet: a signed-in account, and nobody else (docs/wallet.md).

The host names the memory owner (owner.py) only for an account. A wallet call acts for that owner, and only
when it is also whose money the call touches, so the balance a card shows is the one an approval spends."""

from ..errors import DomainError
from ..owner import current_memory_owner, current_owner

ACCOUNT_ONLY = "WALLET_ACCOUNT_ONLY"


def account_of_call() -> str | None:
    """The account this call acts for, or None for a visitor."""
    owner = current_memory_owner()
    return owner if owner is not None and owner == current_owner() else None


def wallet_owner() -> str:
    owner = account_of_call()
    if owner is None:
        raise DomainError(ACCOUNT_ONLY, "A wallet is for signed-in accounts. Sign in to use one.")
    return owner
