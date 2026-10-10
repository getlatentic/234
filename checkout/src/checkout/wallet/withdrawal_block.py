# SPDX-License-Identifier: AGPL-3.0-or-later
"""Whether an owner may withdraw now (docs/wallet.md, disputes): not while any block on them is unlifted.

A block is a row of `wallet_withdrawal_block` (migrations/0014_wallet_withdrawal.sql): a dispute on one of
their top-ups adds one, keyed by the dispute, and lifts it when the dispute ends (getlatentic/planning#641).
Until something adds a row, nobody is blocked.

The rule is held inside the statement that takes a withdrawal's money (withdrawals.py), as `blocked_sql`;
`withdrawals_blocked` is only for saying why a withdrawal was refused, or for refusing one early."""

from ..db import Db


def blocked_sql(owner: str) -> str:
    """True while `owner` (a column or a placeholder of the enclosing statement) has a block not lifted."""
    return (
        f"EXISTS (SELECT 1 FROM wallet_withdrawal_block AS b WHERE b.owner = {owner} AND b.lifted_at IS NULL)"
    )


async def withdrawals_blocked(db: Db, owner: str) -> bool:
    row = await db.row(f"SELECT {blocked_sql('?')} AS blocked", owner)
    return bool(row and row["blocked"])
