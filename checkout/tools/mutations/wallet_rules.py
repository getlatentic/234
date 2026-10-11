# SPDX-License-Identifier: AGPL-3.0-or-later
"""What keeps the wallet's money honest (wallet/journal.py, wallet/spending.py, wallet/freeze.py, and the
journal as migrations/0015_wallet_dispute.sql rebuilt it): no balance below zero, a frozen wallet pays
nothing, the cap bounds funding, a ref moves money once, the journal is append-only, and a quote is paid from
the wallet only with a live hold that is then never given back."""

from tools.mutations.model import AIRTIME, LEDGER_SRC, SRC, Mutation

DISPUTE_TESTS = ["tests/test_wallet_disputes.py"]

WALLET = [
    "tests/test_wallet_journal.py",
    "tests/test_wallet_races.py",
    "tests/test_wallet_spending.py",
    "tests/test_wallet_settings.py",
]
JOURNAL = f"{SRC}/wallet/journal.py"
SPENDING = f"{SRC}/wallet/spending.py"
SCHEMA = "migrations/0015_wallet_dispute.sql"
WALLET_SCHEMA = "migrations/0011_wallet.sql"
FREEZE = f"{SRC}/wallet/freeze.py"


def wallet(name: str, path: str, old: str, new: str, tests: list[str] = WALLET) -> Mutation:
    return Mutation(f"wallet: {name}", path, old, new, tests)


MUTATIONS: list[Mutation] = [
    wallet(
        "a debit lands only while the balance covers it, in one statement",
        JOURNAL,
        'AND {BALANCE_SQL} >= ?{_ON_CONFLICT}",',
        'AND {BALANCE_SQL} >= 0 * ?{_ON_CONFLICT}",',
    ),
    wallet(
        "a frozen wallet pays nothing",
        JOURNAL,
        "WHERE {unfrozen_sql('?')} AND",
        "WHERE ({unfrozen_sql('?')} OR 1) AND",
    ),
    wallet(
        "operations' freeze flag freezes the wallet",
        FREEZE,
        '"(fw.frozen = 1 OR EXISTS',
        '"(fw.frozen = 2 OR EXISTS',
    ),
    wallet(
        "a freeze row freezes the wallet until it is lifted",
        FREEZE,
        "WHERE ff.owner = fw.owner AND ff.lifted_at IS NULL))",
        "WHERE ff.owner = fw.owner AND ff.lifted_at IS NOT NULL))",
        WALLET + DISPUTE_TESTS,
    ),
    wallet(
        "funding stops at the balance cap",
        JOURNAL,
        "{BALANCE_SQL} + ? <= ?){_ON_CONFLICT}",
        "{BALANCE_SQL} + ? <= ? OR 1){_ON_CONFLICT}",
    ),
    wallet(
        "only funding is capped, so money given back always lands",
        JOURNAL,
        "WHERE (? <> '{CAPPED_KIND}' OR",
        "WHERE (? = '' OR",
    ),
    wallet(
        "a ref reused for another amount is refused",
        JOURNAL,
        "if entry.amount_kobo != amount:",
        "if False:",
    ),
    wallet(
        "an amount is a positive whole number of kobo",
        JOURNAL,
        "isinstance(amount, bool) or amount <= 0:",
        "isinstance(amount, bool):",
    ),
    wallet(
        "a kind debits only as a debit",
        JOURNAL,
        "if kind not in DEBIT_KINDS:",
        "if False:",
    ),
    wallet(
        "a ref moves money once (the unique key)",
        SCHEMA,
        "  UNIQUE (owner, kind, ref)\n",
        "  UNIQUE (id, owner, kind, ref)\n",
    ),
    wallet(
        "each kind has its one sign",
        SCHEMA,
        "(kind IN ('spend', 'withdraw', 'dispute') AND sign = -1)",
        "(kind IN ('spend', 'withdraw', 'dispute'))",
    ),
    wallet(
        "an entry is for a positive amount",
        SCHEMA,
        "CHECK (typeof(amount_kobo) = 'integer' AND amount_kobo > 0),\n  ref TEXT",
        "CHECK (typeof(amount_kobo) IN ('integer', 'real')),\n  ref TEXT",
    ),
    wallet(
        "a wallet is an owner key's, never a PACT agent's",
        WALLET_SCHEMA,
        "CHECK (length(owner) = 32 AND owner NOT GLOB '*[^0-9a-f]*')",
        "CHECK (length(owner) > 0)",
    ),
    wallet(
        "an entry cannot be changed",
        SCHEMA,
        "SELECT RAISE(ABORT, 'a wallet entry cannot be changed');",
        "SELECT 1;",
    ),
    wallet(
        "an entry cannot be removed",
        SCHEMA,
        "SELECT RAISE(ABORT, 'a wallet entry cannot be removed');",
        "SELECT 1;",
    ),
    wallet(
        "the wallet's claim needs a hold for this quote and its amount",
        SPENDING,
        '"AND h.ref = quotes.id AND h.amount_kobo = quotes.amount_kobo) "',
        '"AND 1) "',
    ),
    wallet(
        "the wallet's claim refuses a hold that was given back",
        SPENDING,
        "r.kind = 'release'",
        "r.kind = 'none'",
    ),
    wallet(
        "the claim holds the funding source's condition",
        f"{LEDGER_SRC}/approval.py",
        ' AND ({funded.condition})"',
        '"',
    ),
    wallet(
        "a wallet approval marks the quote as paid from the wallet in the same statement",
        SPENDING,
        'WALLET_PAID: dict[str, Any] = {"funding": "wallet", "paymentStatus": "success"}',
        'WALLET_PAID: dict[str, Any] = {"paymentStatus": "success"}',
    ),
    wallet(
        "a release never gives back what a wallet-paid quote spent",
        SPENDING,
        '_NOT_PAID_FROM_WALLET = (\n    "NOT EXISTS',
        '_NOT_PAID_FROM_WALLET = (\n    "1 OR NOT EXISTS',
    ),
    wallet(
        "a refund is only for a quote in refund_due",
        SPENDING,
        "AND q.state = 'refund_due' \"",
        "AND q.state <> '' \"",
    ),
    wallet(
        "a refund is only for a quote the wallet paid",
        SPENDING,
        "\"AND json_extract(q.progress, '$.funding') = 'wallet')\"\n)\n_ON_CONFLICT",
        '"AND 1)"\n)\n_ON_CONFLICT',
    ),
    wallet(
        "a release or refund gives back exactly what the hold took",
        SPENDING,
        "SELECT ?, h.owner, ?, 1, h.amount_kobo, h.ref",
        "SELECT ?, h.owner, ?, 1, h.amount_kobo * 2, h.ref",
    ),
    wallet(
        "a lost claim gives the hold back",
        SPENDING,
        "        if not claimed:\n            await self.release(owner, quote.id)\n",
        "",
    ),
    wallet(
        "a claim that failed gives the hold back",
        SPENDING,
        "        except BaseException:\n            await self.release(owner, quote.id)\n            raise",
        "        except BaseException:\n            raise",
    ),
    wallet(
        "a hold given back is not offered again",
        SPENDING,
        'if await self.journal.entry(owner, "release", quote.id) is not None:',
        "if False:",
    ),
    wallet(
        "a wallet-paid quote starts no checkout",
        f"{SRC}/flows/checkout_leg.py",
        '"checkoutUrl" in quote.progress or paid_from_wallet(quote):',
        '"checkoutUrl" in quote.progress:',
        WALLET + AIRTIME,
    ),
    wallet(
        "a failed wallet-paid order is refunded on the next check",
        f"{SRC}/flows/airtime.py",
        "return await self.present(await refund_to_wallet(self.ctx, quote))",
        "return await self.present(quote)",
        WALLET + AIRTIME,
    ),
]
