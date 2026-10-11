# SPDX-License-Identifier: AGPL-3.0-or-later
"""A provider reversing a delivered order (flows/reversal.py, migrations/0016_quote_reversed.sql, whose
triggers 0019_quote_refund.sql makes again): only a requery that answers reversed moves anything, a delivered
quote becomes reversed and nothing else, once, as its owner, a wallet payment comes back once in the same
batch and only for a reversed quote the wallet paid, the ending is told, and a reversed quote no longer counts
against the day's limits."""

from tools.mutations.model import LEDGER_SRC, SRC, Mutation

REVERSAL = [
    "tests/test_flow_airtime_reversal.py",
    "tests/test_reversal_migration.py",
    "tests/test_vtpass_interpret.py",
    "tests/test_vtpass_sim.py",
]
FLOW = f"{SRC}/flows/reversal.py"
SPENDING = f"{SRC}/wallet/spending.py"
SCHEMA = "migrations/0019_quote_refund.sql"


def reversal(name: str, path: str, old: str, new: str) -> Mutation:
    return Mutation(f"reversal: {name}", path, old, new, REVERSAL)


MUTATIONS: list[Mutation] = [
    reversal(
        "VTpass says reversed only with status reversed",
        f"{SRC}/vtpass/interpret.py",
        'if code in _REVERSAL_CODES and _inner_status(payload) == "reversed":',
        "if code in _REVERSAL_CODES:",
    ),
    reversal(
        "only a requery that answers reversed moves anything",
        FLOW,
        "    if not outcome.reversed:",
        "    if False:",
    ),
    reversal(
        "a callback reporting a reversal of a delivered quote asks VTpass again",
        f"{SRC}/provider_hooks/rechecks.py",
        '        await self.jobs.send({"kind": "reversal", "quote": quote_id})',
        "        pass",
    ),
    reversal(
        "a reversal acts as the quote's owner",
        f"{SRC}/provider_hooks/rechecks.py",
        '        with acting_for(row["owner"]):\n            quote = await reverse_if_confirmed',
        '        with acting_for("f" * 32):\n            quote = await reverse_if_confirmed',
    ),
    reversal(
        "only a settled quote is reversed, by one caller",
        f"{LEDGER_SRC}/progress.py",
        "WHERE id = ? AND owner = ? AND state = 'settled'\",",
        'WHERE id = ? AND owner = ?",',
    ),
    reversal(
        "a delivered quote can only be reversed, and a reversed one stays",
        SCHEMA,
        "WHEN OLD.state <> NEW.state AND (OLD.state = 'reversed' OR",
        "WHEN 0 AND (OLD.state = 'reversed' OR",
    ),
    reversal(
        "a wallet payment comes back in the reversal's own batch",
        FLOW,
        "    refund = [wallet.reversal_refund(ledger.owner(), quote.id)] if wallet else []",
        "    refund = []",
    ),
    reversal(
        "a reversal refund is only for a reversed quote",
        SPENDING,
        "AND q.state = 'reversed' \"",
        "AND q.state <> '' \"",
    ),
    reversal(
        "a reversal refund is only for a quote the wallet paid",
        SPENDING,
        "\"AND json_extract(q.progress, '$.funding') = 'wallet')\"\n)\n_PAID_AND_REFUND_DUE",
        '"AND 1)"\n)\n_PAID_AND_REFUND_DUE',
    ),
    reversal(
        "a reversal is told as a quote's ending",
        SCHEMA,
        "'expired',\n                    'reversed', 'refunded')",
        "'expired',\n                    'refunded')",
    ),
    reversal(
        "a reversed quote no longer counts against the day's limits",
        f"{LEDGER_SRC}/records.py",
        'SPENDING_STATES = ("approved", "settled", "refund_due")',
        'SPENDING_STATES = ("approved", "settled", "refund_due", "reversed")',
    ),
]
