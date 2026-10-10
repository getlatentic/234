# SPDX-License-Identifier: AGPL-3.0-or-later
"""The ledger: limits, expiry, one approval, idempotency, and the once-only writes that hold under races."""

from tools.mutations.model import (
    AIRTIME,
    CONNECTOR_TOOLS,
    FOOD,
    LEDGER,
    LEDGER_SRC,
    PAYMENT,
    Mutation,
)

MUTATIONS: list[Mutation] = [
    Mutation(
        "per-payment limit (quote time)",
        f"{LEDGER_SRC}/spend.py",
        "if amount > self.limits.per_payment_kobo:",
        "if False:",
        LEDGER + PAYMENT,
    ),
    Mutation(
        "per-payment limit (inside the approval statement)",
        f"{LEDGER_SRC}/approval.py",
        '"AND amount_kobo <= ? AND amount_kobo + (SELECT',
        '"AND ? > 0 AND amount_kobo + (SELECT',
        LEDGER + PAYMENT,
    ),
    Mutation(
        "daily limit (quote time)",
        f"{LEDGER_SRC}/spend.py",
        "if spent + amount > self.limits.daily_kobo:",
        "if False:",
        LEDGER + PAYMENT + AIRTIME,
    ),
    Mutation(
        "daily limit (inside the approval statement, so racing approvals cannot both fit)",
        f"{LEDGER_SRC}/approval.py",
        "AND amount_kobo <= ? AND amount_kobo + (SELECT COALESCE(SUM(amount_kobo), 0) ",
        "AND amount_kobo <= ? AND 0 + (SELECT COALESCE(SUM(amount_kobo), 0) ",
        LEDGER + PAYMENT,
    ),
    Mutation(
        "spend from failed and abandoned payments is released",
        f"{LEDGER_SRC}/records.py",
        'SPENDING_STATES = ("approved", "settled", "refund_due")',
        'SPENDING_STATES = ("approved", "settled", "refund_due", "failed", "abandoned")',
        LEDGER + PAYMENT,
    ),
    Mutation(
        "quotes expire (read side)",
        f"{LEDGER_SRC}/store.py",
        'if row["state"] != "open" or self._clock.now() < row["expires_at"]:',
        "if True:",
        LEDGER + PAYMENT,
    ),
    Mutation(
        "quotes expire (inside the approval statement)",
        f"{LEDGER_SRC}/approval.py",
        "AND state = 'open' AND expires_at > ? ",
        "AND state = 'open' AND ? > 0 ",
        LEDGER,
    ),
    Mutation(
        "one approval per quote (inside the approval statement)",
        f"{LEDGER_SRC}/approval.py",
        "AND connector = ? AND state = 'open' AND",
        "AND connector = ? AND",
        LEDGER + PAYMENT,
    ),
    Mutation(
        "the approval's event row is written only when the approval won",
        f"{LEDGER_SRC}/approval.py",
        "WHERE quote_id = ? AND event = 'approval.released'), ? WHERE changes() = 1\",\n                 "
        "   (quote_id, quote_id, now),",
        "WHERE quote_id = ? AND event = 'approval.released'), ? WHERE 1 = 1\",\n                    "
        "(quote_id, quote_id, now),",
        LEDGER,
    ),
    Mutation(
        "a quote cannot be changed once made (database trigger)",
        "migrations/0007_payer_group.sql",
        "BEFORE UPDATE OF connector, kind, amount_kobo, currency, description, merchant, merchant_ref,",
        "BEFORE UPDATE OF connector, kind, merchant_ref,",
        LEDGER,
    ),
    Mutation(
        "an idempotency key cannot be reused for a different request",
        f"{LEDGER_SRC}/making.py",
        'if row["request_hash"] != digest:',
        "if False:",
        LEDGER + PAYMENT,
    ),
    Mutation(
        "a quote belongs to one connector",
        f"{LEDGER_SRC}/store.py",
        "if quote.connector != connector:",
        "if False:",
        LEDGER + PAYMENT + AIRTIME,
    ),
    Mutation(
        "an approval put back is only allowed before a checkout started",
        f"{LEDGER_SRC}/approval.py",
        "\"AND json_extract(progress, '$.checkoutUrl') IS NULL\",\n"
        "                    (quote_id, self.owner()),",
        '"",\n                    (quote_id, self.owner()),',
        LEDGER,
    ),
    Mutation(
        "one caller at a time holds a provider step",
        f"{LEDGER_SRC}/progress.py",
        "\"WHERE id = ? AND owner = ? AND (json_extract(progress, '$.inFlightSince') IS NULL \"",
        '"WHERE id = ? AND owner = ? AND (1 = 1 "',
        LEDGER,
    ),
    Mutation(
        "a progress value is chosen once however many callers race",
        f"{LEDGER_SRC}/progress.py",
        '"WHERE id = ? AND owner = ? AND json_extract(progress, ?) IS NULL",',
        '"WHERE id = ? AND owner = ? AND ? IS NOT NULL",',
        LEDGER + FOOD + AIRTIME,
    ),
    Mutation(
        "progress is patched only while the quote is in the asked state",
        f"{LEDGER_SRC}/progress.py",
        "WHERE id = ? AND owner = ? AND (? IS NULL OR state = ?)",
        "WHERE id = ? AND owner = ? AND (? IS NULL OR ? IS NULL)",
        LEDGER + AIRTIME,
    ),
    Mutation(
        "approval needs the card's token",
        f"{LEDGER_SRC}/approval.py",
        "return hmac.compare_digest(self.approval_token(quote_id), token)",
        "return True",
        LEDGER + PAYMENT + CONNECTOR_TOOLS,
    ),
]
