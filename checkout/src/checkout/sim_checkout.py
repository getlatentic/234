# SPDX-License-Identifier: AGPL-3.0-or-later
"""The simulated Paystack checkout page: a person's stand-in for Paystack's hosted page, served by
the Worker at /sim/checkout/<reference>. It moves no money; a button only finishes the simulated
transaction, and a payment made here is announced as Paystack announces one: a signed `charge.success`
webhook to the connectors' own /hooks/paystack, so the quote is checked again and its ending is an MCP event.
Drop the route in production."""

import json
import re
from datetime import UTC, datetime
from urllib.parse import parse_qs, quote, urlsplit

from .app import App
from .ids import quote_id_of
from .money import format_naira
from .paystack.sim_store import SimTransaction
from .provider_hooks import paystack as paystack_webhook
from .provider_hooks.http import paystack_hook
from .responses import HTML_HEADERS, HttpResponse
from .sim_checkout_page import POLICY, buttons, page, state

PAGE_HEADERS = {
    **HTML_HEADERS,
    "content-security-policy": POLICY,
    "referrer-policy": "same-origin",
    "x-content-type-options": "nosniff",
}
CHAT_PATH = re.compile(r"/c/[0-9a-f]{32}/?")
OUTCOMES = {"success": ("paid", "Paid"), "failed": ("declined", "Declined"), "closed": ("closed", "Closed")}


def _same_origin(app: App, headers: dict[str, str]) -> bool:
    """A finish button posts from this page; a post from another page is refused."""
    origin = headers.get("origin")
    if origin is None:
        return True
    base = urlsplit(app.settings.public_base_url)
    return origin == f"{base.scheme}://{base.netloc}"


def _chat_path(query: str) -> str | None:
    """The chat this checkout was opened from, as a path on the chat host. Only that shape is taken."""
    given = parse_qs(query).get("back", [""])[0]
    return given if CHAT_PATH.fullmatch(given) else None


async def _press(app: App, reference: str, button: str) -> bool:
    """Whether the press changed the transaction. It names one reference and changes that transaction
    only, and only while it is unfinished."""
    sim = app.paystack_sim
    if button == "close":
        return await sim.close_transaction(reference)
    moment = datetime.fromtimestamp(app.clock.now() / 1000, UTC)
    stamp = moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return await sim.finish_transaction(reference, button == "pay", stamp)


async def _what_for(app: App, reference: str, transaction: SimTransaction) -> str:
    """Merchant and description in one line, from the quote the reference was made for."""
    quote_id = quote_id_of(reference)
    held = await app.ledger.checkout_facts(quote_id) if quote_id else None
    description = held.description if held else transaction.description or "Payment"
    if held is None or held.merchant.lower() in description.lower():
        return description
    return f"{held.merchant} · {description}"


async def _announce(app: App, reference: str) -> None:
    """The webhook Paystack sends for a successful charge, signed with the simulator's key and handled by the
    same code a real one is."""
    body = json.dumps(
        {"event": "charge.success", "data": {"reference": reference, "status": "success"}}
    ).encode()
    key = paystack_webhook.simulated_key(app.settings.approval_secret)
    headers = {paystack_webhook.SIGNATURE_HEADER: paystack_webhook.sign(body, key)}
    await paystack_hook(app.background.rechecks, (key,), headers, body)


async def handle_checkout(
    app: App, method: str, path: str, headers: dict[str, str], query: str = ""
) -> HttpResponse:
    parts = path.strip("/").split("/")  # sim / checkout / <reference> [/ pay|decline|close]
    reference = parts[2] if len(parts) >= 3 else ""
    sim = app.paystack_sim
    transaction = await sim.transaction(reference)
    if transaction is None:
        return HttpResponse(404, "Unknown checkout", HTML_HEADERS)
    outcome = None
    if method == "POST" and len(parts) == 4 and parts[3] in ("pay", "decline", "close"):
        if not _same_origin(app, headers):
            return HttpResponse(403, "Refused: this page only takes its own buttons", HTML_HEADERS)
        changed = await _press(app, reference, parts[3])
        transaction = await sim.transaction(reference) or transaction
        outcome = "closed" if parts[3] == "close" else transaction.status
        if changed and quote_id_of(reference) and parts[3] == "pay":
            await _announce(app, reference)
    elif method == "GET":
        await sim.open_transaction(reference)
        transaction = await sim.transaction(reference) or transaction
    outcome = outcome or (transaction.status if transaction.status in ("success", "failed") else None)
    back = _chat_path(query)
    if outcome in OUTCOMES:
        chat = app.settings.host_public_url
        kind, word = OUTCOMES[outcome]
        body = state(kind, word, f"{chat}{back}" if chat and back else None)
    else:
        body = buttons(reference, f"?back={quote(back, safe='/')}" if back else "")
    html = page(
        await _what_for(app, reference, transaction),
        format_naira(transaction.amount_kobo),
        body,
        closing=outcome in OUTCOMES,
    )
    return HttpResponse(200, html, PAGE_HEADERS)
