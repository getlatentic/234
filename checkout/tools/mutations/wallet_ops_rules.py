# SPDX-License-Identifier: AGPL-3.0-or-later
"""What keeps the wallet's operations honest (ops.py, wallet/adjustments.py, wallet/stale_holds.py,
metrics.py): a correction only with the operators' token, a debit that never overdraws or leaves a frozen
wallet, a correction id that moves money once and only on its own terms, a second and different operator
above the threshold; the minute gives back only stale holds that paid no quote, oldest first and bounded; and
recording a movement never fails it."""

from tools.mutations.model import SRC, Mutation

OPS_TESTS = [
    "tests/test_wallet_adjust.py",
    "tests/test_wallet_stale_holds.py",
    "tests/test_wallet_metrics.py",
]
OPS = f"{SRC}/ops.py"
ADJUST = f"{SRC}/wallet/adjustments.py"
REAPER = f"{SRC}/wallet/stale_holds.py"
FAR = " + 1000000000000"


def ops(name: str, path: str, old: str, new: str) -> Mutation:
    return Mutation(f"wallet ops: {name}", path, old, new, OPS_TESTS)


MUTATIONS: list[Mutation] = [
    ops(
        "a Worker without OPS_TOKEN refuses every /ops/ call",
        OPS,
        "return bool(expected) and hmac.compare_digest(",
        "return not expected or hmac.compare_digest(",
    ),
    ops(
        "a call without the right token is refused",
        OPS,
        "return bool(expected) and hmac.compare_digest(",
        "return bool(expected) or hmac.compare_digest(",
    ),
    ops(
        "a correction debit never overdraws",
        ADJUST,
        'f"AND (? = 1 OR {BALANCE_SQL} >= ?) "',
        'f"AND (? = 1 OR {BALANCE_SQL} >= 0 * ?) "',
    ),
    ops(
        "a correction debit never leaves a frozen wallet",
        ADJUST,
        "AND (? = 1 OR frozen = 0)) ",
        "AND (? = 1 OR frozen IN (0, 1))) ",
    ),
    ops(
        "above the threshold one operator moves nothing",
        ADJUST,
        '"AND ((? <= ? AND NOT EXISTS',
        f'"AND ((? <= ?{FAR} AND NOT EXISTS',
    ),
    ops(
        "a correction id moves money once, for one owner",
        ADJUST,
        "NOT EXISTS (SELECT 1 FROM wallet_adjustment WHERE correction_id = ?)) ",
        "NOT EXISTS (SELECT 1 FROM wallet_adjustment WHERE correction_id = ? AND 0)) ",
    ),
    ops(
        "a proposal is applied only on its own terms",
        ADJUST,
        '"AND a.owner = ? AND a.sign = ? AND a.amount_kobo = ? AND a.reason = ? AND',
        '"AND (a.owner = ? AND a.sign = ? AND a.amount_kobo = ? AND a.reason = ? OR 1) AND',
    ),
    ops(
        "the same id with other terms is refused",
        ADJUST,
        "if found is None or found.terms() != asked.terms():",
        "if found is None:",
    ),
    ops(
        "the second operator must differ from the proposer",
        ADJUST,
        "AND a.proposed_by <> ?)) ",
        "AND (a.proposed_by <> ? OR 1))) ",
    ),
    ops(
        "a correction is recorded as applied only with its entry",
        ADJUST,
        '_APPLIED = f"{_RECORD}{_ENTRY_EXISTS} ON CONFLICT',
        '_APPLIED = f"{_RECORD}1 ON CONFLICT',
    ),
    ops(
        "the minute gives back stale holds",
        f"{SRC}/background.py",
        "            await self.stale_holds.release_due()",
        "            pass",
    ),
    ops(
        "a fresh hold is left alone",
        REAPER,
        "\"WHERE h.kind = 'spend' AND h.created_at <= ? \"",
        f"\"WHERE h.kind = 'spend' AND h.created_at <= ?{FAR} \"",
    ),
    ops(
        "a hold that paid a quote is never picked, so it cannot crowd out a stale one",
        REAPER,
        "\"AND json_extract(q.progress, '$.funding') = 'wallet') \"",
        '"AND 0) "',
    ),
    ops(
        "a released hold is not picked again",
        REAPER,
        '"AND r.ref = h.ref) "',
        '"AND r.ref = h.ref AND 0) "',
    ),
    ops("the oldest holds go first", REAPER, '"ORDER BY h.seq LIMIT ?"', '"ORDER BY h.seq DESC LIMIT ?"'),
    ops("each run is bounded", REAPER, '"ORDER BY h.seq LIMIT ?"', '"ORDER BY h.seq LIMIT ? + 100"'),
    ops(
        "recording a movement never fails it",
        f"{SRC}/metrics.py",
        '        except Exception:\n            log.warning("A %s data point could not be written"',
        '        except ZeroDivisionError:\n            log.warning("A %s data point could not be written"',
    ),
]
