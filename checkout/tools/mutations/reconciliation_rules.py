# SPDX-License-Identifier: AGPL-3.0-or-later
"""What keeps the wallet's reconciliation true (wallet/reconciliation.py, books.py, treasury.py,
funding_pause.py, migrations/0018_wallet_reconciliation.sql, the Bachs and Paystack balances): what 234
holds is every provider together, a provider that cannot be read is unknown and never zero, a Bachs balance
counts its pending money and its debt, a short complete run pauses new top-ups and only a complete run lifts
the pause, it runs once an hour, only an operator asks for it, and each run is kept as it was."""

from tools.mutations.model import SRC, Mutation

TESTS = [
    "tests/test_wallet_reconciliation.py",
    "tests/test_bachs_client.py",
    "tests/test_paystack_client.py",
]
SCHEMA = "migrations/0018_wallet_reconciliation.sql"


def rule(name: str, path: str, old: str, new: str) -> Mutation:
    return Mutation(f"reconciliation: {name}", path, old, new, TESTS)


MUTATIONS: list[Mutation] = [
    rule(
        "what 234 owes is the whole journal",
        f"{SRC}/wallet/books.py",
        "(SELECT COALESCE(SUM(sign * amount_kobo), 0) FROM wallet_entry) AS owed",
        "(SELECT COALESCE(SUM(amount_kobo), 0) FROM wallet_entry) AS owed",
    ),
    rule(
        "what lost disputes could not hold is counted",
        f"{SRC}/wallet/books.py",
        "(SELECT COALESCE(SUM(written_off_kobo), 0) FROM wallet_dispute) AS written_off",
        "0 AS written_off",
    ),
    rule(
        "a provider that cannot be read is unknown, never zero",
        f"{SRC}/wallet/treasury.py",
        '            self._audit.log("wallet.reconcile.unread", provider=name, why=str(error)[:120])\n'
        "            return None",
        '            self._audit.log("wallet.reconcile.unread", provider=name, why=str(error)[:120])\n'
        "            return 0",
    ),
    rule(
        "what 234 holds is unknown while any provider is",
        f"{SRC}/wallet/treasury.py",
        "return None if any(part is None for part in parts) else",
        "return None if all(part is None for part in parts) else",
    ),
    rule(
        "VTpass that cannot be read is not read as a balance",
        f"{SRC}/wallet/treasury.py",
        "if check is None or not check.ok or check.balance_kobo is None:",
        "if check is None or check.balance_kobo is None:",
    ),
    rule(
        "the gap is owed less held",
        f"{SRC}/wallet/reconciliation.py",
        "gap = None if total is None else books.owed_kobo - total",
        "gap = None if total is None else books.owed_kobo - total - 1",
    ),
    rule(
        "it runs once an hour",
        f"{SRC}/wallet/reconciliation.py",
        "if last is not None and self._clock.now() - last < EVERY_MS:",
        "if False:",
    ),
    rule(
        "the cron runs it",
        f"{SRC}/background.py",
        "            await self.reconciliation.run_if_due()",
        "            pass",
    ),
    rule(
        "a short run pauses new top-ups",
        f"{SRC}/wallet/topups.py",
        "AND {BALANCE_SQL} + ? <= ? AND {funding_open_sql()}",
        "AND {BALANCE_SQL} + ? <= ?",
    ),
    rule(
        "a run that could not read a provider neither pauses nor lifts",
        f"{SRC}/wallet/funding_pause.py",
        "FROM wallet_reconciliation AS r WHERE r.gap_kobo IS NOT NULL)",
        "FROM wallet_reconciliation AS r)",
    ),
    rule(
        "only a short run pauses",
        f"{SRC}/wallet/funding_pause.py",
        "WHERE seq = {_LATEST_COMPLETE} AND short = 1)",
        "WHERE seq = {_LATEST_COMPLETE})",
    ),
    rule(
        "a paused top-up is refused as paused",
        f"{SRC}/wallet/topups.py",
        "        if await funding_paused(self._db):\n            return DomainError(",
        "        if False:\n            return DomainError(",
    ),
    rule(
        "Bachs' pending money is 234's too",
        f"{SRC}/bachs/client.py",
        "total += available + pending",
        "total += available",
    ),
    rule(
        "a Bachs balance a lost dispute took below zero is a debt",
        f"{SRC}/bachs/client.py",
        'return None if magnitude is None else -magnitude if text.startswith("-") else magnitude',
        "return magnitude",
    ),
    rule(
        "a Bachs balance 234 cannot read is an error",
        f"{SRC}/bachs/client.py",
        'raise BachsError("Bachs wrote an NGN balance 234 cannot read.", False, reply.status)',
        "continue",
    ),
    rule(
        "only NGN at Paystack is counted",
        f"{SRC}/paystack/client.py",
        'return sum(b.balance for b in balances if b.currency == "NGN")',
        "return sum(b.balance for b in balances)",
    ),
    rule(
        "only an operator runs it, and only by GET",
        f"{SRC}/ops.py",
        '        if method != "GET":\n            return HttpResponse(405, "", {"allow": "GET"})',
        '        if False:\n            return HttpResponse(405, "", {"allow": "GET"})',
    ),
    rule(
        "a run is never changed",
        SCHEMA,
        "  SELECT RAISE(ABORT, 'a reconciliation is kept as it was');",
        "  SELECT 1;",
    ),
    rule(
        "a run is never removed",
        SCHEMA,
        "  SELECT RAISE(ABORT, 'a reconciliation cannot be removed');",
        "  SELECT 1;",
    ),
    rule(
        "a run is short exactly when its gap is above zero",
        SCHEMA,
        "  CHECK (short = (gap_kobo IS NOT NULL AND gap_kobo > 0))",
        "  CHECK (short IN (0, 1))",
    ),
]
