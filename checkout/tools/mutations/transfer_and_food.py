# SPDX-License-Identifier: AGPL-3.0-or-later
"""Transfers and the simulated food merchant."""

from tools.mutations.model import (
    FOOD,
    SRC,
    TRANSFER,
    Mutation,
)

MUTATIONS: list[Mutation] = [
    Mutation(
        "refused payouts fail closed, without falling back to the simulator",
        f"{SRC}/flows/transfer.py",
        "if is_payouts_unavailable(error):",
        "if False:",
        TRANSFER,
    ),
    Mutation(
        "a transfer is sent once however many callers approve together",
        f"{SRC}/flows/transfer.py",
        'if not await ledger.acquire_step(quote.id, STEP_STALE_MS, {"transferAttempted": True}):',
        "if False:",
        TRANSFER,
    ),
    Mutation(
        "a retry after a lost reply asks Paystack about the transfer before sending again",
        f"{SRC}/flows/transfer.py",
        'if quote.progress.get("transferAttempted"):',
        "if False:",
        TRANSFER,
    ),
    Mutation(
        "a transfer for another amount than the quote is a refund due",
        f"{SRC}/flows/transfer.py",
        "if outcome.amount_kobo != quote.amount_kobo:",
        "if False:",
        TRANSFER,
    ),
    Mutation(
        "a one-time code is finalized once however many callers submit",
        f"{SRC}/flows/transfer.py",
        "if not await ledger.acquire_step(quote.id, STEP_STALE_MS):\n            raise "
        'DomainError("APPROVAL_IN_PROGRESS", "A code is already being checked',
        'if False:\n            raise DomainError("APPROVAL_IN_PROGRESS", "A code is already being checked',
        TRANSFER,
    ),
    Mutation(
        "a code is refused for a transfer that is not waiting for one",
        f"{SRC}/flows/transfer.py",
        'if quote.state != "approved" or quote.progress.get("transferStatus") != "otp" or code is None:',
        "if False:",
        TRANSFER,
    ),
    Mutation(
        "the recipient's name comes from the bank lookup",
        f"{SRC}/flows/transfer.py",
        "name = await account_holder(self.ctx.paystack, account, chosen.code)",
        "name = note",
        TRANSFER,
    ),
    Mutation(
        "a transfer quote is refused before Paystack is asked when the limit or the words disagree",
        f"{SRC}/flows/transfer.py",
        "            await ledger.assert_quotable(amount_kobo)\n",
        "",
        TRANSFER,
    ),
    Mutation(
        "food is delivered only for a confirmed payment",
        f"{SRC}/flows/food.py",
        'if not checked.paid or checked.quote.state != "approved":',
        'if checked.quote.state != "approved":',
        FOOD,
    ),
    Mutation(
        "the kitchen takes an order once however many callers check together",
        f"{SRC}/flows/food.py",
        'if await ledger.set_progress_once(paid.id, "orderPlacedAt", self.ctx.clock.now()):',
        'if await ledger.patch_progress(paid.id, {"orderPlacedAt": self.ctx.clock.now()}):',
        FOOD,
    ),
]
