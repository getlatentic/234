# SPDX-License-Identifier: AGPL-3.0-or-later
"""What keeps a Paystack refund honest (refunds/, migrations/0019_quote_refund.sql, provider_hooks/, the flows
that end a quote owing one): only a quote paid at the checkout and owing its payer is refunded, only for a
payment Paystack verified as a success of exactly its amount, under that payment's reference, never from the
wallet; it is sent once, never again while Paystack may hold it, decided by Paystack alone, followed by its
event and the minute as its owner, and the quote ends refunded only once Paystack processed it."""

from tools.mutations.model import LEDGER_SRC, SRC, Mutation

REFUND = [
    "tests/test_refunds.py",
    "tests/test_refund_races.py",
    "tests/test_refund_guards.py",
    "tests/test_refund_migration.py",
    "tests/test_paystack_refunds.py",
]
OPENING = f"{SRC}/refunds/opening.py"
OUTCOME = f"{SRC}/refunds/outcome.py"
OWED = f"{SRC}/refunds/owed.py"
SCHEMA = "migrations/0019_quote_refund.sql"
FAR = " + 1000000000000"


def refund(name: str, path: str, old: str, new: str) -> Mutation:
    return Mutation(f"refund: {name}", path, old, new, REFUND)


OPENING_RULES = [
    refund(
        "only a payment Paystack holds as a success is refunded",
        OPENING,
        '    if check.status != "success":',
        "    if False:",
    ),
    refund(
        "only a payment of exactly the quote's amount, in naira, is refunded",
        OPENING,
        '    if check.amount_kobo != quote.amount_kobo or check.currency != "NGN":',
        "    if False:",
    ),
    refund(
        "the statement that opens a refund holds the quote's amount",
        OPENING,
        '"WHERE q.id = ? AND q.amount_kobo = ? AND',
        '"WHERE q.id = ? AND (q.amount_kobo = ? OR 1) AND',
    ),
    refund(
        "the statement that opens a refund holds the payment's reference",
        OPENING,
        "json_extract(q.progress, '$.paystackReference') = ? \"",
        "json_extract(q.progress, '$.paystackReference') <> ? \"",
    ),
    refund(
        "only the caller that opened a refund sends it",
        OPENING,
        "        return Opened(opened, opened)",
        "        return Opened(opened, True)",
    ),
    refund(
        "only a quote owing a refund has one opened",
        OWED,
        "f\"{quote}.state IN ('refund_due', 'reversed') \"",
        "f\"{quote}.state <> '' \"",
    ),
    refund(
        "the statement that opens a refund holds the wallet out",
        OWED,
        "f\"AND json_extract({quote}.progress, '$.funding') IS NOT 'wallet' \"",
        'f"AND 1 "',
    ),
    refund(
        "a quote paid from the wallet is never asked for",
        OWED,
        "        and not paid_from_wallet(quote)\n",
        "        and True\n",
    ),
]

SENDING = [
    refund(
        "a send that may not have reached Paystack stays undecided",
        OUTCOME,
        "        if error.retryable:\n            return await self._unanswered(refund)",
        "        if False:\n            return await self._unanswered(refund)",
    ),
    refund(
        "a refusal is asked about once more before it fails",
        OUTCOME,
        "            found = await self._find(refund)\n        except PaystackError:\n"
        "            return await self._unanswered",
        "            found = None\n        except PaystackError:\n            return await self._unanswered",
    ),
    refund(
        "an answer for another amount or payment decides nothing",
        OUTCOME,
        "        if outcome.amount_kobo != refund.amount_kobo or named not in (None, refund.transaction_id):",
        "        if False:",
    ),
    refund(
        "a send in flight is not sent again",
        OUTCOME,
        "(sending_since IS NULL OR sending_since <= ?)",
        "(1 OR sending_since <= ?)",
    ),
    refund(
        "a processed refund ends only an owed quote refunded",
        OUTCOME,
        "WHERE id = ? AND state = 'refund_due' \"",
        "WHERE id = ? AND state <> '' \"",
    ),
    refund(
        "a quote ends refunded only once its refund is processed",
        OUTCOME,
        "AND r.state = 'processed')\"\n)",
        "AND r.state <> '')\"\n)",
    ),
    refund(
        "the quote's progress mirrors its refund, for the card",
        OUTCOME,
        "                (_MIRROR, (refund.quote_id,)),\n",
        "",
    ),
    refund(
        "the minute opens an owed refund that was never started",
        OUTCOME,
        '        return [row["id"] for row in never] + [row["quote_id"] for row in undecided]',
        '        return [row["quote_id"] for row in undecided]',
    ),
    refund(
        "the minute asks again about every undecided refund",
        OUTCOME,
        '        return [row["id"] for row in never] + [row["quote_id"] for row in undecided]',
        '        return [row["id"] for row in never]',
    ),
    refund(
        "the minute waits before opening an owed refund",
        OUTCOME,
        "AND q.settled_at < ? ",
        f"AND q.settled_at < ?{FAR} ",
    ),
]

FOLLOWING = [
    refund(
        "Paystack's refund events reach the refund they name",
        f"{SRC}/provider_hooks/http.py",
        "    refund = paystack.refund_of(raw)",
        "    refund = None",
    ),
    refund(
        "a refund event asks only about an undecided refund",
        f"{SRC}/provider_hooks/rechecks.py",
        "        if refund is None or refund.state not in UNDECIDED or self.jobs is None:",
        "        if self.jobs is None:",
    ),
    refund(
        "a refund is followed as its quote's owner",
        f"{SRC}/provider_hooks/rechecks.py",
        '        with acting_for(row["owner"]):\n            found = await self.refunds.follow',
        '        with acting_for("f" * 32):\n            found = await self.refunds.follow',
    ),
    refund(
        "an airtime order paid and not delivered asks for its refund",
        f"{SRC}/flows/airtime.py",
        "                    return await ask_refund(self.ctx, owed)",
        "                    return owed",
    ),
    refund(
        "a payment landing after the checkout closed asks for its refund",
        f"{SRC}/flows/checkout_leg.py",
        "        return PaymentCheck(await ask_refund(ctx, owed), False)",
        "        return PaymentCheck(owed, False)",
    ),
    refund(
        "a reversed order paid at the checkout asks for its refund",
        f"{SRC}/flows/reversal.py",
        "    return await ask_refund(ctx, reversed_quote)",
        "    return reversed_quote",
    ),
    refund(
        "a refunded quote no longer counts against the day's limits",
        f"{LEDGER_SRC}/records.py",
        'SPENDING_STATES = ("approved", "settled", "refund_due")',
        'SPENDING_STATES = ("approved", "settled", "refund_due", "refunded")',
    ),
    refund(
        "the card says refunded only once Paystack processed it",
        f"{SRC}/refunds/words.py",
        '    return quote.state == "refunded" or refund_state(quote) == "processed"',
        '    return quote.state == "refunded" or refund_state(quote) is not None',
    ),
    refund(
        "the simulated Paystack never refunds more than the payment",
        f"{SRC}/paystack/sim_store.py",
        '    "<= t.amount_kobo"',
        f'    "<= t.amount_kobo{FAR}"',
    ),
]

DATABASE = [
    refund(
        "a refund keeps its quote, amount and transaction",
        SCHEMA,
        "SELECT RAISE(ABORT, 'a refund keeps its quote, amount and transaction');",
        "SELECT 1;",
    ),
    refund(
        "a refund keeps the Paystack refund it was given",
        SCHEMA,
        "SELECT RAISE(ABORT, 'a refund keeps the Paystack refund it was given');",
        "SELECT 1;",
    ),
    refund(
        "a decided refund stays decided",
        SCHEMA,
        "SELECT RAISE(ABORT, 'a decided refund stays decided');",
        "SELECT 1;",
    ),
    refund(
        "a refund is decided exactly when it has a decision",
        SCHEMA,
        "  CHECK ((state IN ('processed', 'failed', 'refused')) = (decided_at IS NOT NULL)),",
        "  CHECK (1),",
    ),
    refund(
        "a quote is refunded only once its refund is processed, and stays refunded",
        SCHEMA,
        "WHEN OLD.state <> NEW.state AND (OLD.state = 'refunded' OR",
        "WHEN 0 AND (OLD.state = 'refunded' OR",
    ),
    refund(
        "a refund is told as a quote's ending",
        SCHEMA,
        "'expired',\n                    'reversed', 'refunded')",
        "'expired',\n                    'reversed')",
    ),
]

MUTATIONS: list[Mutation] = [*OPENING_RULES, *SENDING, *FOLLOWING, *DATABASE]
