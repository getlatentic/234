# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared by the withdrawal tests: a funded wallet, a withdrawal started and approved as the card does it,
Paystack's transfer events as Paystack signs them, and the simulated transfer moved on as Paystack would."""

import json

from checkout.http import handle
from checkout.paystack.api import PaystackApi
from checkout.provider_hooks import paystack
from checkout.wallet.withdrawal_record import Withdrawal
from checkout.wallet.withdrawals import Withdrawals
from tests.support import ALICE, Stack

SECRET = "test-secret-not-real"
ACCOUNT = "0123456789"
NAME = "SIMULATED ACCOUNT 6789"
BANK = "GTBank"


def withdrawals(stack: Stack) -> Withdrawals:
    return stack.app.withdrawals


async def funded(stack: Stack, amount: int = 10_000_000, owner: str = ALICE, ref: str = "top-up-1") -> None:
    journal = withdrawals(stack).journal
    await journal.open(owner)
    assert await journal.credit(owner, "fund", amount, ref) is not None


async def started(
    stack: Stack, amount: int = 2_000_000, owner: str = ALICE, account: str = ACCOUNT
) -> Withdrawal:
    return await withdrawals(stack).start(owner, amount, BANK, account)


async def approved(stack: Stack, withdrawal: Withdrawal, name: str | None = None) -> Withdrawal:
    token = withdrawals(stack).token(withdrawal.id)
    return await withdrawals(stack).approve(
        withdrawal.owner, withdrawal.id, token, withdrawal.amount_kobo, name or withdrawal.account_name
    )


async def balance(stack: Stack, owner: str = ALICE) -> int:
    return await withdrawals(stack).journal.balance(owner)


async def kinds(stack: Stack, owner: str = ALICE) -> list[str]:
    rows = await stack.rows("SELECT kind FROM wallet_entry WHERE owner = ? ORDER BY seq", owner)
    return [row["kind"] for row in rows]


async def state_of(stack: Stack, withdrawal: Withdrawal) -> str:
    found = await withdrawals(stack).get(withdrawal.owner, withdrawal.id)
    assert found is not None
    return found.state


async def set_transfer(stack: Stack, withdrawal: Withdrawal, status: str) -> None:
    """Paystack's side of a transfer moving on: pending, success, failed or reversed."""
    await stack.db.execute("UPDATE sim_transfers SET status = ? WHERE reference = ?", status, withdrawal.id)


def transfer_event(withdrawal: Withdrawal, event: str) -> bytes:
    data = {"reference": withdrawal.id, "status": event.split(".")[1], "amount": withdrawal.amount_kobo}
    return json.dumps({"event": event, "data": data}).encode()


async def paystack_event(stack: Stack, withdrawal: Withdrawal, event: str):
    body = transfer_event(withdrawal, event)
    signature = paystack.sign(body, paystack.simulated_key(SECRET))
    return await handle(stack.app, "POST", "/hooks/paystack", {"x-paystack-signature": signature}, body)


def with_paystack(stack: Stack, api: PaystackApi) -> None:
    """The stack's withdrawals over another Paystack (one that fails or answers late)."""
    audit = stack.app.contexts["send-money"].audit
    rebuilt = Withdrawals(stack.db, stack.clock, withdrawals(stack).journal, api, SECRET, audit)
    object.__setattr__(stack.app, "withdrawals", rebuilt)
    stack.app.background.rechecks.withdrawals = rebuilt.outcomes
