# SPDX-License-Identifier: AGPL-3.0-or-later
"""The wallet a draw's account starts with: money added the way a person adds it, through the wallet card's
top-up and the simulated Bachs page, whose signed `collection.succeeded` credits the wallet by the webhook's
own path (docs/wallet.md). No model is involved, and no test route writes the journal."""

import secrets
from urllib.parse import urlsplit

import httpx

from .signed_in import SetupFailed, account_call

WALLET = "wallet"


async def fund_wallet(checkout: str, owner: str, kobo: int) -> None:
    """The account's new wallet holds exactly `kobo` (whole naira, at least one top-up): one top-up of it,
    paid on the simulated Bachs page; then the balance is read back."""
    card = {"card_id": secrets.token_hex(16)}
    async with httpx.AsyncClient(timeout=30) as http:
        if kobo:
            started = await account_call(
                http, checkout, WALLET, owner, "start_topup", {**card, "amount_naira": kobo // 100}
            )
            page = urlsplit(started["structuredContent"]["topup"]["checkoutUrl"]).path
            paid = await http.post(f"{checkout}{page}/pay")
            if paid.status_code != 200:
                raise SetupFailed(f"the simulated Bachs page refused the payment: HTTP {paid.status_code}")
        view = await account_call(http, checkout, WALLET, owner, "wallet_view", card)
    held = view["structuredContent"]["wallet"]["balanceKobo"]
    if held != kobo:
        raise SetupFailed(f"the wallet holds {held} kobo, the case needs {kobo}")
