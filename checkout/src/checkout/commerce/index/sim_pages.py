# SPDX-License-Identifier: AGPL-3.0-or-later
"""The page where a person signs in at the simulated Index, served by the Worker at /sim/index/authorize (a
browser opens it, so it cannot be the simulator's `Transport`). It asks what Index's page asks, whether 234 may
use the account, checks the request as Index's authorization server does (a registered client and redirect
address, PKCE S256), and sends the browser back to the redirect address with a code, or with `access_denied`.
Both answers carry the `state` unchanged. Drop the route, with the other /sim/ pages, in a public deployment."""

import base64
import hashlib
from html import escape
from urllib.parse import urlencode

from ...responses import HTML_HEADERS, HttpResponse
from ...sim_checkout_page import CSS
from ...tokens_css import FAVICON_URI
from .sim_store import IndexSimStore

FORM_FIELDS = ("client_id", "redirect_uri", "state", "code_challenge")
STYLE = CSS + ".lead{margin:.25rem 0 1.75rem;font-size:1.25rem;font-weight:500}"
DIGEST = "'sha256-" + base64.b64encode(hashlib.sha256(STYLE.encode()).digest()).decode() + "'"
POLICY = f"default-src 'none'; style-src {DIGEST}; img-src data:; base-uri 'none'; frame-ancestors 'none'"
HEADERS = {**HTML_HEADERS, "content-security-policy": POLICY, "referrer-policy": "same-origin"}
PAGE = """<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="color-scheme" content="light dark">
<link rel="icon" href="{favicon}">
<title>Paystack Index (simulated)</title>
<style>{css}</style>
<main>
<p class="mode"><span class="dot" aria-hidden="true"></span>Simulated: this is not Paystack Index</p>
<h1 class="who">234 asks to use your Paystack Index account</h1>
<p class="lead">It could pay for what you approve in the chat, from your Zap balance.</p>
<form method="post" action="{base}/authorize/decision">{hidden}
<div class="actions">
<button class="primary" name="decision" value="allow">Allow 234</button>
<button class="quiet" name="decision" value="deny">Not now</button>
</div></form>
</main>
</html>"""


def _refused(why: str) -> HttpResponse:
    return HttpResponse(400, f"<!doctype html><title>Refused</title><p>{escape(why)}", HTML_HEADERS)


async def _problem(store: IndexSimStore, form: dict[str, str]) -> str | None:
    """Why this is not a request the authorization server would take, or None."""
    client = await store.client(form.get("client_id", ""))
    if client is None:
        return "Unknown client."
    if form.get("redirect_uri") not in client["redirect_uris"]:
        return "The redirect address is not one this client registered."
    if form.get("response_type", "code") != "code" or form.get("code_challenge_method", "S256") != "S256":
        return "Only the authorization code with S256 PKCE is taken."
    if not form.get("code_challenge") or not form.get("state"):
        return "A code challenge and a state are required."
    return None


def _hidden(form: dict[str, str]) -> str:
    return "".join(f'<input type="hidden" name="{n}" value="{escape(form.get(n, ""))}">' for n in FORM_FIELDS)


async def show(store: IndexSimStore, base: str, query: dict[str, str]) -> HttpResponse:
    if (why := await _problem(store, query)) is not None:
        return _refused(why)
    html = PAGE.format(favicon=FAVICON_URI, css=STYLE, base=base, hidden=_hidden(query))
    return HttpResponse(200, html, HEADERS)


def _back(form: dict[str, str], **answer: str) -> HttpResponse:
    target = f"{form['redirect_uri']}?{urlencode({**answer, 'state': form['state']})}"
    return HttpResponse(
        302, "", {"location": target, "cache-control": "no-store", "referrer-policy": "no-referrer"}
    )


async def decide(store: IndexSimStore, form: dict[str, str]) -> HttpResponse:
    if (why := await _problem(store, form)) is not None:
        return _refused(why)
    if form.get("decision") != "allow":
        return _back(form, error="access_denied")
    account = await store.new_account()
    code = await store.issue_code(form["client_id"], account.id, form["redirect_uri"], form["code_challenge"])
    return _back(form, code=code)
