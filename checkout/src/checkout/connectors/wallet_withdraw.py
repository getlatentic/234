# SPDX-License-Identifier: AGPL-3.0-or-later
"""Withdrawing on the wallet card (docs/wallet.md, "Withdrawing"), as the card sees it. Both withdrawal
tools are the card's alone: the model has no tool that starts or approves a withdrawal, so money leaves a
wallet only when the person presses Withdraw under the name the bank gave.

`start_withdrawal` resolves the account and opens the withdrawal; its token, for this withdrawal only, is in
`_meta`, which the host hands the card and never keeps or shows a model. `withdraw` carries that token, the
amount the card showed and the name the person confirmed."""

from typing import Annotated

from pydantic import Field

from ..mcp.registry import ToolResult
from ..wallet.withdrawal_record import Withdrawal, withdrawal_view

MIN_WITHDRAWAL_NAIRA = 100
TOKEN_META = "withdrawalToken"

WithdrawalId = Annotated[str, Field(pattern=r"^wd-[0-9a-f]{20}$", description="The withdrawal's id.")]
OUT_HINTS = {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True, "openWorldHint": True}


def outcome_text(withdrawal: Withdrawal) -> str:
    view = withdrawal_view(withdrawal)
    return f"{view['status']}: {view['amount']} to {view['accountName']}, {view['bank']}."


def with_token(result: ToolResult, token: str) -> ToolResult:
    return {**result, "_meta": {TOKEN_META: token}}
