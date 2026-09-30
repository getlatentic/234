# SPDX-License-Identifier: AGPL-3.0-or-later
"""The signed payment webhook to the chat host, and the simulated checkout page that triggers it."""

from tools.mutations.model import SRC, Mutation

WEBHOOK = ["tests/test_webhook.py"]
PAGE = ["tests/test_sim_checkout_page.py"]

MUTATIONS: list[Mutation] = [
    Mutation(
        "the chat host is told when the checkout records a payment",
        f"{SRC}/sim_checkout.py",
        "if changed and quote_id and parts[3] in NOTIFYING_BUTTONS:",
        "if False:",
        WEBHOOK,
    ),
    Mutation(
        "the chat host is told once, not on every repeated press",
        f"{SRC}/sim_checkout.py",
        "if changed and quote_id and",
        "if quote_id and",
        WEBHOOK,
    ),
    Mutation(
        "opening or closing the checkout page does not tell the chat host",
        f"{SRC}/sim_checkout.py",
        'NOTIFYING_BUTTONS = ("pay", "decline")',
        'NOTIFYING_BUTTONS = ("pay", "decline", "close")',
        WEBHOOK,
    ),
    Mutation(
        "the webhook is signed with the shared secret",
        f"{SRC}/webhook.py",
        "SIGNATURE_HEADER: sign(body, self._settings.secret),",
        'SIGNATURE_HEADER: "sha256=",',
        WEBHOOK,
    ),
    Mutation(
        "a failing webhook never breaks the payment",
        f"{SRC}/webhook.py",
        "except Exception as error:",
        "except ZeroDivisionError as error:",
        WEBHOOK,
    ),
    Mutation(
        "a host that never answers is given up on",
        f"{SRC}/webhook.py",
        "                self._timeout,\n            )\n        except",
        "                3600,\n            )\n        except",
        WEBHOOK,
    ),
    Mutation(
        "the webhook address must be the host's payment hook",
        f"{SRC}/config.py",
        "or parts.path != WEBHOOK_PATH:",
        "or False:",
        WEBHOOK,
    ),
    Mutation(
        "the webhook goes over https, or plain http only to this machine",
        f"{SRC}/config.py",
        'local = parts.scheme == "http" and parts.hostname in _LOOPBACK',
        'local = parts.scheme == "http"',
        WEBHOOK,
    ),
    Mutation(
        "the webhook address carries no query, fragment or credentials",
        f"{SRC}/config.py",
        "if parts.query or parts.fragment or parts.username or parts.password:",
        "if False:",
        WEBHOOK,
    ),
    Mutation(
        "the checkout page links back only to a chat path",
        f"{SRC}/sim_checkout.py",
        "return given if CHAT_PATH.fullmatch(given) else None",
        "return given or None",
        PAGE,
    ),
    Mutation(
        "the checkout page carries a policy of its own",
        f"{SRC}/sim_checkout.py",
        '    "content-security-policy": POLICY,\n',
        "",
        PAGE,
    ),
    Mutation(
        "the checkout page escapes what the model wrote",
        f"{SRC}/sim_checkout_page.py",
        "css=CSS, favicon=FAVICON_URI, who=escape(who), amount=escape(amount), body=body, script=script",
        "css=CSS, favicon=FAVICON_URI, who=who, amount=amount, body=body, script=script",
        PAGE,
    ),
]
