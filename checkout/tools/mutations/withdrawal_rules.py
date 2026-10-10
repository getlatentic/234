# SPDX-License-Identifier: AGPL-3.0-or-later
"""What keeps a wallet withdrawal honest (wallet/withdrawals.py, wallet/withdrawal_outcome.py,
migrations/0014_wallet_withdrawal.sql, provider_hooks/): money leaves only on the card's token, under the name
the bank gave and the amount shown, while the withdrawal is the owner's and not expired, within both caps,
from a wallet that covers it and is neither frozen nor blocked; the transfer is decided by Paystack alone,
gives money back once and only for a failed or reversed transfer, and is never sent twice."""

from tools.mutations.model import SRC, Mutation

WITHDRAW = [
    "tests/test_wallet_withdrawals.py",
    "tests/test_wallet_withdrawal_races.py",
    "tests/test_wallet_withdrawal_outcomes.py",
    "tests/test_wallet_withdraw_connector.py",
]
START = f"{SRC}/wallet/withdrawals.py"
OUTCOME = f"{SRC}/wallet/withdrawal_outcome.py"
SCHEMA = "migrations/0014_wallet_withdrawal.sql"
FAR = " + 1000000000000"
LET_GO_ON_NO_ANSWER = "        except PaystackError:\n            return await self._let_go("


def withdraw(name: str, path: str, old: str, new: str) -> Mutation:
    return Mutation(f"withdraw: {name}", path, old, new, WITHDRAW)


TAKING = [
    withdraw(
        "only the card's token approves",
        START,
        "if not hmac.compare_digest(self.token(withdrawal_id), token):",
        "if False:",
    ),
    withdraw(
        "the money is taken only from the owner's own withdrawal",
        START,
        '"WHERE w.id = ? AND w.owner = ? AND',
        '"WHERE w.id = ? AND (w.owner = ? OR 1) AND',
    ),
    withdraw(
        "an expired withdrawal takes nothing", START, "AND w.expires_at > ? ", "AND w.expires_at > 0 * ? "
    ),
    withdraw(
        "the amount taken is the amount the card showed",
        START,
        '"AND w.amount_kobo = ? AND',
        '"AND (w.amount_kobo = ? OR 1) AND',
    ),
    withdraw(
        "the person confirmed the bank's name",
        START,
        "AND w.account_name = ? AND",
        "AND (w.account_name = ? OR 1) AND",
    ),
    withdraw(
        "one withdrawal is at most the cap when the money is taken",
        START,
        "AND w.amount_kobo <= ? ",
        f"AND w.amount_kobo <= ?{FAR} ",
    ),
    withdraw(
        "a frozen wallet sends nothing",
        START,
        "v.owner = w.owner AND v.frozen = 0)",
        "v.owner = w.owner AND v.frozen IN (0, 1))",
    ),
    withdraw("a blocked owner sends nothing", START, "f\"AND NOT {blocked_sql('w.owner')} \"", '"AND 1 "'),
    withdraw(
        "the balance covers the withdrawal, in the statement that takes it",
        START,
        '"WHERE e.owner = w.owner) >= w.amount_kobo "',
        '"WHERE e.owner = w.owner) >= 0 "',
    ),
    withdraw(
        "the daily cap is held in the statement that takes the money",
        START,
        "{withdrawn_since('w.owner')} <= ? \"",
        f"{{withdrawn_since('w.owner')}} <= ?{FAR} \"",
    ),
    withdraw(
        "a withdrawal is sent only once its money is taken",
        START,
        "\"AND e.kind = 'withdraw' AND e.ref = wallet_withdrawal.id \"",
        '"AND e.kind IS NOT NULL "',
    ),
    withdraw(
        "the daily cap does not count money given back",
        f"{SRC}/wallet/journal.py",
        "AND b.kind = 'withdraw_back' AND b.ref = d.ref))",
        "AND b.kind = 'never' AND b.ref = d.ref))",
    ),
]

DECIDING = [
    withdraw(
        "money comes back only for a failed or reversed transfer",
        OUTCOME,
        'AND d.ref = ? AND w.state IN ({_GIVEN_BACK_SQL}) "',
        'AND d.ref = ? "',
    ),
    withdraw(
        "only an undecided withdrawal is decided",
        OUTCOME,
        "else f\"('{UNDECIDED}')\"",
        "else f\"('{UNDECIDED}', 'succeeded')\"",
    ),
    withdraw(
        "an answer for another reference or amount decides nothing",
        OUTCOME,
        "if outcome.reference != withdrawal.id or outcome.amount_kobo != withdrawal.amount_kobo:",
        "if False:",
    ),
    withdraw(
        "a refusal is asked about once more before it fails",
        OUTCOME,
        f"            found = await self._find(withdrawal)\n{LET_GO_ON_NO_ANSWER}",
        f"            found = None\n{LET_GO_ON_NO_ANSWER}",
    ),
    withdraw(
        "a send that may not have reached Paystack stays undecided",
        OUTCOME,
        "        if error.retryable:\n            return await self._let_go(",
        "        if False:\n            return await self._let_go(",
    ),
    withdraw(
        "a transfer Paystack answered for is never sent again",
        OUTCOME,
        "AND transfer_code IS NULL AND",
        "AND",
    ),
    withdraw(
        "a send in flight is not sent again",
        OUTCOME,
        "(sending_since IS NULL OR sending_since <= ?)",
        "(1 OR sending_since <= ?)",
    ),
    withdraw(
        "the minute waits before asking about a withdrawal",
        OUTCOME,
        "AND name_confirmed_at < ? ",
        f"AND name_confirmed_at < ?{FAR} ",
    ),
    withdraw(
        "a decided withdrawal stays decided in the database",
        SCHEMA,
        "OLD.state IN ('expired', 'failed', 'reversed')",
        "OLD.state IN ('expired')",
    ),
    withdraw(
        "Paystack's transfer events reach the withdrawal they name",
        f"{SRC}/provider_hooks/paystack.py",
        "return withdrawal_id_in(reference) or quote_id_in(reference)",
        "return quote_id_in(reference)",
    ),
    withdraw(
        "the minute asks about every undecided withdrawal",
        f"{SRC}/provider_hooks/rechecks.py",
        "for withdrawal_id in await self.withdrawals.undecided_ids():",
        "for withdrawal_id in []:",
    ),
    withdraw(
        "the minute expires open withdrawals",
        f"{SRC}/provider_hooks/rechecks.py",
        "await self.withdrawals.expire_due()",
        "None",
    ),
]

MUTATIONS: list[Mutation] = [*TAKING, *DECIDING]
