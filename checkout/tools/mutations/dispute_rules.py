# SPDX-License-Identifier: AGPL-3.0-or-later
"""What keeps a dispute on a top-up honest (wallet/disputes.py, bachs/disputes.py, provider_hooks/bachs.py,
wallet/topup_credit.py, migrations/0015_wallet_dispute.sql): a dispute opens only on a credited top-up's
charge, in naira, for at most its amount; the hold is what the wallet has up to that amount, taken once and
never below ₦0; a hold that fell short freezes the wallet; withdrawals are blocked while it is open; only won
or closed write back, exactly the hold; a loss writes off just the shortfall; each ending lifts the dispute's
own block and freeze; and a decided dispute stays decided."""

from tools.mutations.model import SRC, Mutation

DISPUTE = [
    "tests/test_wallet_disputes.py",
    "tests/test_wallet_dispute_races.py",
    "tests/test_wallet_dispute_migration.py",
    "tests/test_bachs_sim_dispute.py",
]
DISPUTES = f"{SRC}/wallet/disputes.py"
SCHEMA = "migrations/0015_wallet_dispute.sql"


def dispute(name: str, path: str, old: str, new: str) -> Mutation:
    return Mutation(f"dispute: {name}", path, old, new, DISPUTE)


OPENED = [
    dispute(
        "a dispute opens only on the charge of a credited top-up",
        DISPUTES,
        '"WHERE t.charge_id = ? AND',
        '"WHERE (t.charge_id = ? OR 1) AND',
    ),
    dispute("a dispute opens only in naira", DISPUTES, "AND ? = 'NGN' AND", "AND ? IS NOT NULL AND"),
    dispute(
        "a dispute is for at most the top-up's amount",
        DISPUTES,
        "AND ? BETWEEN 1 AND t.amount_kobo ",
        "AND ? BETWEEN 1 AND t.amount_kobo * 2 ",
    ),
    dispute(
        "the hold is at most what the wallet has",
        DISPUTES,
        "MIN(d.amount_kobo, {_BALANCE})",
        "d.amount_kobo",
    ),
    dispute(
        "a hold opened short is not added to by a later event",
        DISPUTES,
        "FROM wallet_freeze AS f WHERE f.owner = d.owner",
        "FROM wallet_freeze AS f WHERE 0 AND f.owner = d.owner",
    ),
    dispute(
        "a decided dispute holds, blocks and freezes nothing again",
        DISPUTES,
        "WHERE d.id = ? AND d.state = 'open'\"",
        'WHERE d.id = ?"',
    ),
    dispute("an open dispute blocks withdrawals", DISPUTES, "            (_BLOCK, (now, dispute_id)),\n", ""),
    dispute("a short hold freezes the wallet", DISPUTES, "            (_FREEZE, (now, dispute_id)),\n", ""),
    dispute(
        "only a hold short of the amount freezes",
        DISPUTES,
        "AND {_HELD.format(d='d')} < d.amount_kobo ",
        "AND {_HELD.format(d='d')} <= d.amount_kobo ",
    ),
]

DECIDED = [
    dispute(
        "a dispute is decided once",
        DISPUTES,
        "\"WHERE id = ? AND state = 'open'\"",
        '"WHERE id = ?"',
    ),
    dispute(
        "only won and closed write the hold back",
        DISPUTES,
        'f"AND d.state IN ({_in(KEPT_BY_234)})) "',
        "\"AND d.state <> 'open') \"",
    ),
    dispute(
        "the write-back is exactly what the hold took",
        DISPUTES,
        "'dispute_back', 1, h.amount_kobo,",
        "'dispute_back', 1, h.amount_kobo + 1,",
    ),
    dispute(
        "only a loss writes anything off",
        DISPUTES,
        "CASE WHEN ? IN ({_in(LOST_BY_234)})",
        "CASE WHEN ? IS NOT NULL",
    ),
    dispute(
        "a loss writes off only what the hold could not cover",
        DISPUTES,
        "THEN amount_kobo - {_HELD.format(d='wallet_dispute')} ELSE 0 END",
        "THEN amount_kobo ELSE 0 END",
    ),
    dispute(
        "the decision lifts the block",
        DISPUTES,
        '            (_lift("wallet_withdrawal_block"), (now, dispute_id, dispute_id)),\n',
        "",
    ),
    dispute(
        "the decision lifts the freeze",
        DISPUTES,
        '            (_lift("wallet_freeze"), (now, dispute_id, dispute_id)),\n',
        "",
    ),
    dispute(
        "a dispute lifts only its own block and freeze",
        DISPUTES,
        "AND ref = ? AND lifted_at IS NULL ",
        "AND (ref = ? OR 1) AND lifted_at IS NULL ",
    ),
    dispute(
        "closed gives the money back as won does",
        f"{SRC}/bachs/disputes.py",
        'KEPT_BY_234 = frozenset({"won", "closed"})',
        'KEPT_BY_234 = frozenset({"won"})',
    ),
    dispute(
        "an open status decides nothing",
        f"{SRC}/bachs/disputes.py",
        "return self.status if self.status in KEPT_BY_234 | LOST_BY_234 else None",
        "return self.status",
    ),
    dispute(
        "only dispute events are read as disputes",
        f"{SRC}/bachs/disputes.py",
        "event = event_of(raw, DISPUTE_EVENTS)",
        'event = event_of(raw, (*DISPUTE_EVENTS, "collection.succeeded"))',
    ),
    dispute(
        "Bachs' dispute events reach the wallet",
        f"{SRC}/provider_hooks/bachs.py",
        "        if dispute is not None:\n            await self.disputes.settle(dispute)",
        "        if False:\n            await self.disputes.settle(dispute)",
    ),
    dispute(
        "the card says withdrawals are paused",
        f"{SRC}/wallet/view.py",
        '"withdrawalsBlocked": await withdrawals_blocked(self._db, owner),',
        '"withdrawalsBlocked": False,',
    ),
]

KEPT = [
    dispute(
        "a charge another top-up holds is not taken",
        f"{SRC}/wallet/topup_credit.py",
        "WHERE o.charge_id = ?) AND",
        "WHERE o.charge_id = ? AND 0) AND",
    ),
    dispute(
        "a decided dispute stays decided in the database",
        SCHEMA,
        "SELECT RAISE(ABORT, 'a decided dispute stays decided');",
        "SELECT 1;",
    ),
    dispute(
        "a dispute keeps its top-up and amount in the database",
        SCHEMA,
        "SELECT RAISE(ABORT, 'a dispute keeps its top-up and amount');",
        "SELECT 1;",
    ),
    dispute(
        "a top-up keeps its charge", SCHEMA, "SELECT RAISE(ABORT, 'a top-up keeps its charge');", "SELECT 1;"
    ),
    dispute(
        "only a lost dispute carries a write-off",
        SCHEMA,
        "CHECK (state IN ('lost', 'prevented') OR written_off_kobo = 0)",
        "CHECK (1)",
    ),
]

MUTATIONS: list[Mutation] = [*OPENED, *DECIDED, *KEPT]
