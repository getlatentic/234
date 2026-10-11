# SPDX-License-Identifier: AGPL-3.0-or-later
"""Whether a wallet is frozen (migrations/0015_wallet_dispute.sql): `wallet.frozen`, set by operations, or any
`wallet_freeze` row not lifted, such as a dispute whose hold fell short. A frozen wallet pays nothing, takes
no top-up and sends no withdrawal; money given back still lands.

Every statement that moves money out holds the rule in its own WHERE, as `unfrozen_sql`; `wallet_frozen` is
only for saying why something was refused, and for the wallet card."""

from ..db import Db

_FROZEN = (
    "(fw.frozen = 1 OR EXISTS (SELECT 1 FROM wallet_freeze AS ff "
    "WHERE ff.owner = fw.owner AND ff.lifted_at IS NULL))"
)


def unfrozen_sql(owner: str) -> str:
    """True while `owner` (a column or a placeholder of the enclosing statement) has a wallet that is not
    frozen."""
    return f"EXISTS (SELECT 1 FROM wallet AS fw WHERE fw.owner = {owner} AND NOT {_FROZEN})"


async def wallet_frozen(db: Db, owner: str) -> bool | None:
    """Whether the owner's wallet is frozen now; None when they have no wallet."""
    row = await db.row(f"SELECT {_FROZEN} AS frozen FROM wallet AS fw WHERE fw.owner = ?", owner)
    return bool(row["frozen"]) if row else None
