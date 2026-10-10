# SPDX-License-Identifier: AGPL-3.0-or-later
"""What keeps a wallet top-up honest (wallet/topups.py, wallet/topup_credit.py, bachs/,
provider_hooks/bachs.py, sim_bachs.py): only a webhook Bachs signed, recently, credits; only for the checkout,
owner and exact amount 234 made it for; once; within the cap; for a signed-in owner whose wallet is not
frozen; and never on live Bachs."""

from tools.mutations.model import SRC, Mutation

TOPUP = [
    "tests/test_bachs_signature.py",
    "tests/test_bachs_client.py",
    "tests/test_bachs_settings.py",
    "tests/test_bachs_sim_page.py",
    "tests/test_wallet_topups.py",
    "tests/test_wallet_topup_credit.py",
]
SIGNATURE = f"{SRC}/bachs/signature.py"
HOOK = f"{SRC}/provider_hooks/bachs.py"
CREDIT = f"{SRC}/wallet/topup_credit.py"
TOPUPS = f"{SRC}/wallet/topups.py"
SETTINGS = f"{SRC}/bachs/settings.py"


def topup(name: str, path: str, old: str, new: str) -> Mutation:
    return Mutation(f"topup: {name}", path, old, new, TOPUP)


SIGNED = [
    topup("a webhook's v1 must match", SIGNATURE, "if not _matches(", "if False and not _matches("),
    topup(
        "the signature covers the raw body",
        SIGNATURE,
        '"{timestamp}.".encode() + raw',
        '"{timestamp}.".encode()',
    ),
    topup("any v1 in the header may match", SIGNATURE, "for got in given:", "for got in given[:1]:"),
    topup(
        "any configured secret may match",
        SIGNATURE,
        "sign(s, timestamp, raw) for s in secrets]",
        "sign(s, timestamp, raw) for s in secrets[:1]]",
    ),
    topup(
        "a delivery older than five minutes is refused", SIGNATURE, "if age > TOLERANCE_SECONDS:", "if False:"
    ),
    topup("a delivery dated ahead is refused", SIGNATURE, "if age < -FUTURE_SKEW_SECONDS:", "if False:"),
    topup("an unverified delivery is answered 400", HOOK, "if verdict is not Verdict.GENUINE:", "if False:"),
    topup("an oversized body is refused unread", HOOK, "if len(raw) > MAX_BODY:", "if False:"),
    topup("a refused credit is answered 503", HOOK, "is Outcome.OVER_CAP:", "is None:"),
    topup(
        "only collection.succeeded is acted on",
        f"{SRC}/bachs/events.py",
        ' or event.get("type") != COLLECTION_SUCCEEDED:',
        ":",
    ),
    topup(
        "sandbox takes only the endpoint's secret",
        f"{SRC}/funding.py",
        "(bachs.webhook_secret,), None",
        "(bachs.webhook_secret, simulated_webhook_secret(settings.approval_secret)), None",
    ),
]

MATCHED = [
    topup(
        "the collection is for 234's checkout",
        CREDIT,
        "or collection.checkout_id != topup.provider_ref:",
        ":",
    ),
    topup(
        "a top-up with no checkout is paid by none",
        CREDIT,
        "if topup.provider_ref is None or collection",
        "if collection",
    ),
    topup(
        "the collection is for the top-up's owner",
        CREDIT,
        "if collection.owner_tag != owner_tag(",
        "if None == (",
    ),
    topup("only a full collection credits", CREDIT, "if collection.status != FULL_COLLECTION:", "if False:"),
    topup("only naira credits", CREDIT, "if collection.currency != NGN:", "if False:"),
    topup(
        "the amount is exactly the top-up's",
        CREDIT,
        "if collection.amount_kobo != topup.amount_kobo:",
        "if False:",
    ),
    topup(
        "an amount is read only in Bachs' shape",
        f"{SRC}/bachs/api.py",
        "_NAIRA.fullmatch(text)",
        "_NAIRA.match(text)",
    ),
    topup("a top-up is marked paid once", CREDIT, "AND state <> 'paid' ", ""),
]

STARTED = [
    topup(
        "only a signed-in owner's wallet takes a top-up",
        TOPUPS,
        "WHERE EXISTS (SELECT 1 FROM wallet WHERE owner = ? AND frozen = 0) ",
        "WHERE NOT EXISTS (SELECT 1 FROM wallet WHERE owner = ? AND frozen = 1) ",
    ),
    topup("a frozen wallet takes no top-up", TOPUPS, "AND frozen = 0) ", "AND frozen IN (0, 1)) "),
    topup(
        "a top-up fits under the cap when it starts",
        TOPUPS,
        'f"AND {BALANCE_SQL} + ? <= ?"',
        'f"AND {BALANCE_SQL} + ? <= ? + 1000000000"',
    ),
    topup(
        "a top-up is a positive amount",
        TOPUPS,
        "isinstance(amount, bool) or amount <= 0:",
        "isinstance(amount, bool):",
    ),
    topup("the owner key never goes to Bachs", TOPUPS, "OWNER_TAG: owner_tag(owner)", "OWNER_TAG: owner"),
    topup(
        "a checkout Bachs could not make leaves the top-up expired",
        TOPUPS,
        "SET state = 'expired' WHERE id = ? AND state = 'open'\"",
        "SET state = 'open' WHERE id = ? AND state = 'open'\"",
    ),
    topup("an open top-up expires with its checkout", TOPUPS, "AND expires_at <= ?", "AND expires_at < ?"),
    topup(
        "the reference is the Idempotency-Key",
        f"{SRC}/bachs/client.py",
        '"Idempotency-Key": request.reference,',
        '"Idempotency-Key": "fixed",',
    ),
    topup(
        "the stand-in takes only its own page's press",
        f"{SRC}/sim_bachs.py",
        "if action and not same_origin(app, headers):",
        "if False:",
    ),
    topup(
        "the stand-in pays only an unexpired checkout",
        f"{SRC}/bachs/sim_store.py",
        "AND expires_at > ?",
        "AND ? IS NOT NULL",
    ),
]

NOT_LIVE = [
    topup("BACHS_MODE=live refuses to start", SETTINGS, 'if raw == "live":', "if False:"),
    topup("a live Bachs key is refused", SETTINGS, "if key.startswith(LIVE_KEY_PREFIX):", "if False:"),
    topup("only a sandbox key is accepted", SETTINGS, "if not _SANDBOX_KEY.fullmatch(key):", "if False:"),
    topup(
        "sandbox needs the webhook secret",
        SETTINGS,
        "if len(secret) < MIN_WEBHOOK_SECRET_LENGTH:",
        "if False:",
    ),
    topup(
        "the client takes only a sandbox key",
        f"{SRC}/bachs/client.py",
        "if not secret_key.startswith(SANDBOX_KEY_PREFIX):",
        "if False:",
    ),
]

MUTATIONS: list[Mutation] = [*SIGNED, *MATCHED, *STARTED, *NOT_LIVE]
