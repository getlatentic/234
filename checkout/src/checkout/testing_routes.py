# SPDX-License-Identifier: AGPL-3.0-or-later
"""Routes the tests use to look inside the Worker and to run the controls that prove a race test can
fail. Reachable only when ENABLE_TEST_ROUTES=1."""

from contextlib import nullcontext
from typing import Any
from urllib.parse import parse_qs, urlsplit

from .app import App
from .naive import naive_approve
from .owner import acting_for, is_owner_key
from .provider_hooks.http import vtpass_hook
from .responses import HttpResponse, json_response
from .sim_bachs_dispute import raise_dispute
from .sim_index import handle_index_test
from .sim_merchant_order import move_merchant_order
from .sim_paystack_refund import move_refund
from .transport import TransportError, WorkerFetch
from .vtpass.sim import reversal_update
from .vtpass.sim_store import VtpassSimStore

RESET_TABLES = (
    "account_check",
    "sim_merchant_order",
    "quote_events",
    "quote_refund",
    "quotes",
    "sim_transfers",
    "sim_recipients",
    "sim_refunds",
    "sim_transactions",
    "sim_vtpass",
    "memory_proposal",
    "memory_entry",
)
_INSERT_PROBE = (
    "INSERT INTO sim_transactions (reference, amount_kobo, currency, email, status, description)"
    " VALUES (?, 1, 'NGN', 'a@b', ?, 'probe')"
)
LOCAL_HOSTS = ("localhost", "127.0.0.1")


async def _summary(app: App) -> HttpResponse:
    """Every quote is counted; `spentTodayKobo` is the acting owner's alone."""
    db = app.db
    budget = await app.ledger.budget()
    approvals = await db.rows(
        "SELECT quote_id, COUNT(*) AS n FROM quote_events WHERE event = 'approval.claimed' GROUP BY quote_id"
    )
    by_state = await db.rows(
        "SELECT state, COUNT(*) AS n, SUM(amount_kobo) AS kobo FROM quotes GROUP BY state"
    )
    return json_response(
        {
            "spentTodayKobo": budget.spent_today_kobo,
            "dailyLimitKobo": budget.daily_kobo,
            "claimedEvents": {a["quote_id"]: a["n"] for a in approvals},
            "byState": {r["state"]: {"n": r["n"], "kobo": r["kobo"]} for r in by_state},
            "vtpassOrders": (await db.row("SELECT COUNT(*) AS n FROM sim_vtpass"))["n"],
            "transfers": (await db.row("SELECT COUNT(*) AS n FROM sim_transfers"))["n"],
        }
    )


async def _batch_rollback_probe(app: App) -> dict[str, Any]:
    """Does a failing statement roll the whole D1 batch back? Inserts a row, then violates a CHECK."""
    outcome = "no error"
    try:
        await app.db.batch(
            [(_INSERT_PROBE, ("rb-1", "abandoned")), (_INSERT_PROBE, ("rb-2", "not-a-status"))]
        )
    except Exception as error:
        outcome = str(error)[:120]
    survivors = await app.db.rows("SELECT reference FROM sim_transactions WHERE reference LIKE 'rb-%'")
    return {"error": outcome, "rowsLeft": [r["reference"] for r in survivors]}


async def _fetch_probe(url: str) -> HttpResponse:
    """The Workers `fetch` transport reaching a local address, since no provider is ever called in tests."""
    if urlsplit(url).hostname not in LOCAL_HOSTS:
        return HttpResponse(400, "Only local addresses")
    try:
        reply = await WorkerFetch().send("GET", url, headers={"X-Probe": "1"}, body=None, timeout_seconds=5)
    except TransportError as error:
        return json_response({"transportError": str(error)})
    return json_response({"status": reply.status, "body": reply.body, "contentType": reply.content_type})


async def _reverse_vtpass_order(app: App, request_id: str) -> HttpResponse:
    """The simulated VTpass takes back an order it delivered and sends the transaction-update callback for it,
    through the same hook VTpass's own reaches."""
    order = await VtpassSimStore(app.db).reverse(request_id, app.clock.now())
    if order is None:
        return HttpResponse(404, "No delivered order")
    return await vtpass_hook(app.background.rechecks, reversal_update(order, app.clock.now()))


async def handle_test(app: App, method: str, path: str, query: str) -> HttpResponse:
    """`?owner=` acts for that owner in the routes that read or write as one."""
    owner = parse_qs(query).get("owner", [""])[0]
    if owner and not is_owner_key(owner):
        return HttpResponse(400, "An owner is 32 lowercase hex characters")
    with acting_for(owner) if owner else nullcontext():
        return await _route(app, method, path, query)


async def _route(app: App, method: str, path: str, query: str) -> HttpResponse:
    parts = path.strip("/").split("/")
    match method, parts[1:]:
        case "POST", ["reset"]:
            for table in RESET_TABLES:
                await app.db.execute(f"DELETE FROM {table}")
            return json_response({"ok": True})
        case "POST", ["naive-approve", quote_id]:
            return json_response({"approved": await naive_approve(app.ledger, quote_id)})
        case "POST", ["batch-rollback"]:
            return json_response(await _batch_rollback_probe(app))
        case "GET", ["summary"]:
            return await _summary(app)
        case "GET", ["fetch-probe"]:
            return await _fetch_probe(parse_qs(query).get("url", [""])[0])
        case _:
            return await _provider_route(app, method, parts[1:], query)


async def _provider_route(app: App, method: str, parts: list[str], query: str) -> HttpResponse:
    """The routes that move a simulated provider on: each answers as the provider would."""
    asked = {name: values[0] for name, values in parse_qs(query).items()}
    match method, parts:
        case "POST", ["vtpass-reverse", request_id]:
            return await _reverse_vtpass_order(app, request_id)
        case "POST", ["paystack-refund", reference]:
            return await move_refund(app, reference, asked.get("status", "processed"))
        case "POST", ["merchant-order", quote_id]:
            return await move_merchant_order(app, quote_id, asked.get("outcome", "delivered"))
        case _, ["index", *rest]:
            return await handle_index_test(app, method, rest, asked)
        case "POST", ["bachs-dispute", checkout_id]:
            event, status = asked.get("event", "dispute.created"), asked.get("status", "needs_response")
            return await raise_dispute(app, checkout_id, event, status, asked.get("amount"))
        case _:
            return HttpResponse(404, "No such test route")
