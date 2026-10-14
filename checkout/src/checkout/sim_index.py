# SPDX-License-Identifier: AGPL-3.0-or-later
"""The simulated Index's pages and test controls on the Worker: the sign-in page at /sim/index/authorize
(commerce/index/sim_pages.py), and, where ENABLE_TEST_ROUTES is on, the routes that set how the simulated
Index behaves and show what it was asked (`/test/index/...`). Its OAuth and MCP addresses are not served here:
234 reaches them in the Worker, through the simulator's `Transport`."""

from urllib.parse import parse_qsl

from .app import App
from .commerce.index.sim_pages import decide, show
from .commerce.index.sim_store import IndexSimStore
from .commerce.index.sim_tools_base import OUTCOME_SETTING, OUTCOMES
from .responses import HTML_HEADERS, HttpResponse, json_response
from .sim_checkout import same_origin

SETTINGS = {"revocation": ("0", "1"), "sse": ("0", "1"), OUTCOME_SETTING: OUTCOMES}
ACCOUNT_COLUMNS = {"zap_kobo": int, "zap_linked": int, "chowdeck_linked": int}


def _store(app: App) -> IndexSimStore | None:
    parts = app.contexts["merchants"].index
    return parts.sim if parts else None


async def handle_index_page(
    app: App, method: str, parts: list[str], headers: dict[str, str], raw: bytes, query: str
) -> HttpResponse:
    """/sim/index/authorize (GET) and /sim/index/authorize/decision (POST)."""
    store, index = _store(app), app.contexts["merchants"].index
    if store is None or index is None or parts[2:3] != ["authorize"]:
        return HttpResponse(404, "Not found", HTML_HEADERS)
    if method == "GET" and len(parts) == 3:
        return await show(store, index.base, dict(parse_qsl(query)))
    if method == "POST" and parts[3:] == ["decision"]:
        if not same_origin(app, headers):
            return HttpResponse(403, "Refused: this page only takes its own buttons", HTML_HEADERS)
        return await decide(store, dict(parse_qsl(raw.decode())))
    return HttpResponse(404, "Not found", HTML_HEADERS)


async def _set_account(store: IndexSimStore, asked: dict[str, str]) -> HttpResponse:
    account = await store.latest_account()
    if account is None:
        return HttpResponse(404, "No simulated Index account has signed in yet")
    changes = {name: kind(asked[name]) for name, kind in ACCOUNT_COLUMNS.items() if name in asked}
    await store.set_account(account.id, **changes)
    return json_response({"account": account.id, "changed": sorted(changes)})


async def _set_setting(store: IndexSimStore, asked: dict[str, str]) -> HttpResponse:
    name, value = asked.get("name", ""), asked.get("value", "")
    if value not in SETTINGS.get(name, ()):
        return HttpResponse(400, f"Settings: {', '.join(f'{n}={"|".join(v)}' for n, v in SETTINGS.items())}")
    await store.set_setting(name, value)
    return json_response({name: value})


async def handle_index_test(app: App, method: str, parts: list[str], asked: dict[str, str]) -> HttpResponse:
    """/test/index/<what>: set the latest account, a setting, expire or revoke the tokens, read the calls."""
    store = _store(app)
    if store is None:
        return HttpResponse(404, "Index is live: there is no simulator to move")
    match method, parts:
        case "POST", ["account"]:
            return await _set_account(store, asked)
        case "POST", ["setting"]:
            return await _set_setting(store, asked)
        case "POST", ["expire"]:
            await store.expire_access_tokens()
            return json_response({"expired": "access"})
        case "POST", ["revoke"]:
            await store.revoke_all()
            return json_response({"revoked": "all"})
        case "GET", ["calls"]:
            return json_response({"calls": await store.calls()})
        case _:
            return HttpResponse(404, "No such test route")
