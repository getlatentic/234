# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared by the wallet tests: a journal on the in-memory database, and money put into a wallet."""

from checkout.owner import DEFAULT_OWNER
from checkout.sqlite_db import SqliteDb
from checkout.wallet.journal import Journal
from checkout.wallet.settings import WalletSettings
from tests.support import FakeClock, Stack

CAP = 20_000_000


def new_journal(cap: int = CAP) -> Journal:
    return Journal(SqliteDb(), FakeClock(), WalletSettings(balance_cap_kobo=cap))


def journal_of(stack: Stack) -> Journal:
    wallet = stack.app.contexts["airtime"].wallet
    assert wallet is not None
    return wallet.journal


async def fund(stack: Stack, amount: int, owner: str = DEFAULT_OWNER, ref: str = "top-up-1") -> None:
    assert await journal_of(stack).credit(owner, "fund", amount, ref) is not None


async def entries(stack: Stack, kind: str | None = None) -> list[dict]:
    if kind is None:
        return await stack.rows("SELECT * FROM wallet_entry ORDER BY seq")
    return await stack.rows("SELECT * FROM wallet_entry WHERE kind = ? ORDER BY seq", kind)
