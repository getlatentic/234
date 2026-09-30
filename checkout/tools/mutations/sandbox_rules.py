# SPDX-License-Identifier: AGPL-3.0-or-later
"""The card sandbox's guards and the connectors' answers to it: what a resource may ask of the sandbox and
what the host grants, the Paystack popup's access code, and the two eras of MCP. The host's tests run in the
host's environment; the sandbox Worker's own rules (its headers, its policy) are JavaScript and are checked
by `node --test sandbox/test` and by the browser conformance runs."""

from tools.mutations.model import SRC, Mutation
from tools.mutations.model import host_mutation as host

CSP = ["tests/test_card_csp.py"]
HUB = ["tests/test_hub.py"]
INLINE = ["tests/test_inline_checkout.py"]
MODERN = ["tests/test_mcp_modern.py"]


def checkout(guardrail: str, file: str, find: str, replace: str, tests: list[str]) -> Mutation:
    return Mutation(guardrail, f"{SRC}/{file}", find, replace, tests)


MUTATIONS: list[Mutation] = [
    host(
        "an origin a card declares must be a plain https (or wss) origin",
        "chat/card_csp.py",
        "if not _SOURCES[name].fullmatch(entry):",
        "if False:",
        CSP,
    ),
    host(
        "an origin a card declares must be on the host's allowlist",
        "chat/card_csp.py",
        "if reason is None and not policy.permits(server, name, entry):",
        "if False:",
        CSP,
    ),
    host(
        "a trusted connector's image origins are plain: no wildcard",
        "chat/card_csp.py",
        'and "*" not in entry',
        "",
        CSP,
    ),
    host(
        "a card gets at most sixteen origins a field",
        "chat/card_csp.py",
        'reason = "more than 16 entries" if len(kept) >= MAX_ENTRIES else refusal(name, entry)',
        "reason = refusal(name, entry)",
        CSP,
    ),
    host(
        "a card is given a browser feature only when the host grants it",
        "chat/card_csp.py",
        "if name in asked and name in granted}",
        "if name in asked}",
        CSP,
    ),
    host(
        "a card runs on the sandbox origin only when it embeds an approved frame",
        "chat/card_csp.py",
        'return SANDBOX_ON_SANDBOX_ORIGIN if self.csp.get("frameDomains") else SANDBOX_OPAQUE',
        "return SANDBOX_ON_SANDBOX_ORIGIN",
        CSP,
    ),
    host(
        "a page may frame the sandbox's origin and, where sign-in is on, the auth domain: nothing else",
        "chat/security.py",
        '[settings.SANDBOX_ORIGIN] if name == "frame-src" and settings.SANDBOX_ORIGIN else []',
        '["*"] if name == "frame-src" else []',
        CSP,
    ),
    host(
        "the sandbox cannot be the host's own origin",
        "config/settings.py",
        "if SANDBOX_ORIGIN and SANDBOX_ORIGIN == PUBLIC_BASE_URL:",
        "if False:",
        CSP,
    ),
    host(
        "a host without a signing key shows no card",
        "chat/views/cards.py",
        "if signature is None:",
        "if False:",
        CSP,
    ),
    host(
        "a card's notes to the model have a limit of their own",
        "chat/views/send.py",
        'kinds.CARD_CONTEXT, f"note:{request.owner}")',
        "kinds.CARD_CONTEXT, None)",
        ["tests/test_views.py"],
    ),
    host(
        "a card is an MCP App resource",
        "turns/hub.py",
        'if content.get("mimeType") != MIME_TYPE:',
        "if False:",
        HUB,
    ),
    host(
        "the content's metadata wins over the listing's",
        "turns/hub.py",
        "_ui_meta(content) or _ui_meta(listed[uri])",
        "_ui_meta(listed[uri]) or _ui_meta(content)",
        HUB,
    ),
    checkout(
        "the access code goes to the card only while the person is at the checkout",
        "flows/base.py",
        'waiting = quote.state == "approved" and quote.progress.get("paymentStatus") != "success"',
        "waiting = True",
        INLINE,
    ),
    checkout(
        "the access code is handed out only where the popup can run",
        "flows/base.py",
        "if not self.ctx.inline_checkout:\n            return None",
        "if False:\n            return None",
        INLINE,
    ),
    checkout(
        "the access code is kept only where the popup can run",
        "flows/checkout_leg.py",
        "    if ctx.inline_checkout:\n        progress",
        "    if True:\n        progress",
        INLINE,
    ),
    checkout(
        "the model's status tool never carries the access code",
        "connectors/kit.py",
        'return card_result({**view, "checkoutUrl": None}, summarise(view))',
        'return card_result({**view, "checkoutUrl": None}, summarise(view), '
        "await self.flow.card_meta(args.quote_id))",
        INLINE,
    ),
    checkout(
        "the approval card asks for Paystack's origins only where the popup can run",
        "connectors/kit.py",
        "(INLINE_CHECKOUT_CSP if self.ctx.inline_checkout else {})",
        "INLINE_CHECKOUT_CSP",
        INLINE,
    ),
    checkout(
        "the Paystack key can go only to Paystack or to this machine",
        "config.py",
        "if raw != PAYSTACK_API_URL and not (here and plain):",
        "if False:",
        INLINE,
    ),
    checkout(
        "extra card origins are a test setting",
        "config.py",
        'if env.text("ENABLE_TEST_ROUTES") != "1":',
        "if False:",
        INLINE,
    ),
    checkout(
        "a request that names a browser origin is refused",
        "http.py",
        "if origin is not None and origin not in app.settings.mcp_allowed_origins:",
        "if False:",
        MODERN,
    ),
    checkout(
        "a stateless request must carry its version and capabilities in _meta",
        "mcp/modern.py",
        "if version is None or CAPABILITIES_KEY not in meta:",
        "if False:",
        MODERN,
    ),
    checkout(
        "the version header must match the version in _meta",
        "mcp/modern.py",
        "if header != version:",
        "if False:",
        MODERN,
    ),
    checkout(
        "the method header must match the method in the body",
        "mcp/modern.py",
        'if headers.get("mcp-method") != method:',
        "if False:",
        MODERN,
    ),
    checkout(
        "the name header must match the tool or resource in the body",
        "mcp/modern.py",
        "if given is None or _decoded(given) != wanted:",
        "if False:",
        MODERN,
    ),
]
