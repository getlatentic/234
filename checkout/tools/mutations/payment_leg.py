# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Paystack payment leg every connector shares, and the simulated checkout page."""

from tools.mutations.model import (
    PAYMENT,
    SRC,
    Mutation,
)

MUTATIONS: list[Mutation] = [
    Mutation(
        "a payment is only accepted for the quoted amount and currency",
        f"{SRC}/flows/checkout_leg.py",
        'if check.amount_kobo != quote.amount_kobo or check.currency != "NGN":',
        "if False:",
        PAYMENT,
    ),
    Mutation(
        "an unpaid checkout is not given up on early",
        f"{SRC}/flows/checkout_leg.py",
        'give_up = _past_window(ctx, quote) or (checkout_closed and check.status == "abandoned")',
        "give_up = True",
        PAYMENT,
    ),
    Mutation(
        "a checkout that is being paid is not given up on when the person says it was closed",
        f"{SRC}/flows/checkout_leg.py",
        'or (checkout_closed and check.status == "abandoned")',
        "or checkout_closed",
        PAYMENT,
    ),
    Mutation(
        "a payment arriving after the checkout was closed is a refund due",
        f"{SRC}/flows/checkout_leg.py",
        'if quote.state == "abandoned":\n        return "The payment arrived after the checkout had been '
        'closed."',
        'if False:\n        return "The payment arrived after the checkout had been closed."',
        PAYMENT,
    ),
    Mutation(
        "the approval is put back when Paystack cannot start the checkout",
        f"{SRC}/flows/checkout_leg.py",
        "        await ledger.release_approval(quote.id)\n",
        "",
        PAYMENT,
    ),
    Mutation(
        "only one checkout is started when approvals race",
        f"{SRC}/flows/checkout_leg.py",
        "if not await ledger.acquire_step(quote.id, STEP_STALE_MS):\n        raise DomainError(\n        "
        '    "APPROVAL_IN_PROGRESS"',
        'if False:\n        raise DomainError(\n            "APPROVAL_IN_PROGRESS"',
        [*PAYMENT, "tests/test_ledger.py"],
    ),
    Mutation(
        "the simulated checkout page refuses a post from another origin",
        f"{SRC}/sim_checkout.py",
        'return origin == f"{base.scheme}://{base.netloc}"',
        "return True",
        ["tests/test_paystack_sim.py"],
    ),
    Mutation(
        "a finished simulated payment cannot be changed by a second click",
        f"{SRC}/paystack/sim_store.py",
        "\"WHERE reference = ? AND status IN ('abandoned', 'ongoing')\",",
        '"WHERE reference = ?",',
        ["tests/test_paystack_sim.py"],
    ),
]
