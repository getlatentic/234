# SPDX-License-Identifier: AGPL-3.0-or-later
"""The markup of the simulated checkout page: one narrow column in the cards' visual language (the design
tokens, the dot line, a large tabular amount), light and dark by the reader's setting.

The page is served with a policy that lets in exactly this stylesheet and this script, by hash."""

import base64
import hashlib
from html import escape

from .tokens_css import FAVICON_URI, TOKENS_CSS

PAGE_CSS = """
*{box-sizing:border-box}
body{margin:0;min-height:100dvh;display:grid;justify-items:center;align-content:start;background:var(--ground);
color:var(--ink);font:1rem/1.4 var(--stack-sans);
padding:calc(max(1.5rem,env(safe-area-inset-top)) + 14dvh) max(1rem,env(safe-area-inset-right))
max(1.5rem,env(safe-area-inset-bottom)) max(1rem,env(safe-area-inset-left))}
main{width:min(100%,22rem)}
.mode{display:flex;align-items:center;gap:.375rem;margin:0 0 1.5rem;font-size:.75rem;color:var(--ink-3)}
.dot{width:.375rem;height:.375rem;flex:none;border-radius:50%;background:var(--ink-3)}
.who{margin:0;font-size:1rem;font-weight:500;overflow-wrap:anywhere}
.amount{margin:.25rem 0 1.75rem;font-size:clamp(2.25rem,13vw,3rem);line-height:1;font-weight:600;
letter-spacing:-.025em;font-variant-numeric:tabular-nums;overflow-wrap:anywhere}
.actions{display:grid;gap:.5rem}
form{margin:0}
button,.back{display:flex;align-items:center;justify-content:center;width:100%;min-height:2.75rem;
padding:.625rem 1rem;border-radius:var(--r-control);font:inherit;text-align:center;cursor:pointer;
text-decoration:none;outline-offset:2px}
button:focus-visible,.back:focus-visible{outline:2px solid var(--primary)}
.primary{border:0;background:var(--primary);color:var(--on-primary);font-weight:600}
.secondary{border:1px solid var(--line-strong);background:transparent;color:var(--ink)}
.quiet{border:0;background:transparent;color:var(--ink-2);font-size:.875rem}
.back{justify-content:flex-start;padding-inline:0;color:var(--ink);font-weight:500;
text-decoration:underline;text-underline-offset:.2em}
@media (hover:hover){.primary:hover{background:var(--primary-hover)}
.primary:active{background:var(--primary-pressed)}.secondary:hover{background:var(--sunken)}
.quiet:hover{color:var(--ink)}}
.state{display:flex;align-items:center;gap:.5rem;margin:0 0 1rem;padding:.625rem .75rem;
border-radius:var(--r-control);
background:var(--sunken);font-weight:500}
.state svg{width:1.25rem;height:1.25rem;flex:none;fill:none;stroke:currentColor;stroke-width:2;
stroke-linecap:round;stroke-linejoin:round}
.state.paid{background:var(--ok-soft);color:var(--ok)}.state.declined{background:var(--bad-soft);color:var(--bad)}
.state.closed{color:var(--ink-2)}
"""
CSS = TOKENS_CSS + PAGE_CSS

CLOSE_SCRIPT = "setTimeout(function(){window.close()},1200)"

GLYPHS = {
    "paid": '<circle cx="10" cy="10" r="8"/><path d="M6.5 10.5l2.5 2.5 4.5-5.5"/>',
    "declined": '<circle cx="10" cy="10" r="8"/><path d="M10 6v5M10 13.75v.01"/>',
    "closed": '<circle cx="10" cy="10" r="8"/><path d="M7 10h6"/>',
}

PAGE = """<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="color-scheme" content="light dark">
<link rel="icon" href="{favicon}">
<title>{title}</title>
<style>{css}</style>
<main>
<p class="mode"><span class="dot" aria-hidden="true"></span>Simulated: no money moves</p>
<h1 class="who">{who}</h1>
<p class="amount">{amount}</p>
{body}
</main>
{script}
</html>"""

FORM = (
    '<form method="post" action="{base}/{ref}/{action}{query}">'
    '<button class="{style}">{label}</button></form>'
)
CHOICES = (
    ("pay", "primary", "Pay with a test card"),
    ("decline", "secondary", "Use a declined card"),
    ("close", "quiet", "Close without paying"),
)

STATE = (
    '<p class="state {kind}" role="status"><svg viewBox="0 0 20 20" aria-hidden="true">{glyph}</svg>'
    "<span>{word}</span></p>\n{link}"
)


def _digest(source: str) -> str:
    return "'sha256-" + base64.b64encode(hashlib.sha256(source.encode()).digest()).decode() + "'"


POLICY = (
    f"default-src 'none'; style-src {_digest(CSS)}; script-src {_digest(CLOSE_SCRIPT)}; img-src data:; "
    "form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
)


def buttons(
    reference: str,
    query: str,
    base: str = "/sim/checkout",
    choices: tuple[tuple[str, str, str], ...] = CHOICES,
) -> str:
    forms = (
        FORM.format(
            base=base, ref=escape(reference), action=action, query=escape(query), style=style, label=label
        )
        for action, style, label in choices
    )
    return '<div class="actions">\n' + "\n".join(forms) + "\n</div>"


def state(kind: str, word: str, chat_url: str | None) -> str:
    link = f'<a class="back" href="{escape(chat_url)}">Return to the chat</a>' if chat_url else ""
    return STATE.format(kind=kind, glyph=GLYPHS[kind], word=word, link=link)


def page(
    who: str, amount: str, body: str, *, closing: bool, title: str = "Simulated Paystack checkout"
) -> str:
    script = f"<script>{CLOSE_SCRIPT}</script>" if closing else ""
    return PAGE.format(
        title=escape(title),
        css=CSS,
        favicon=FAVICON_URI,
        who=escape(who),
        amount=escape(amount),
        body=body,
        script=script,
    )
