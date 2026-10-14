# SPDX-License-Identifier: AGPL-3.0-or-later
"""The rules the server holds whatever the model says (docs/commerce.md, "Rules the server holds"; commerce/,
connectors/merchants.py, flows/merchants.py, flows/merchant_leg.py, migrations/0020_commerce.sql): prices come
from the offers alone and an amount only for an open or ranged offer within its limits; a quote needs a
merchant of the directory; third-party words are cleaned; the approval is bound to a digest of the whole
quote; an account is checked where the provider says so; an order is placed once and ends delivered, refunded
or pending; the free-text payment tool is offered only while no provider is live."""

from tools.mutations.model import SRC, Mutation

PRICING = ["tests/test_commerce_pricing.py", "tests/test_commerce_directory.py"]
FIELDS = ["tests/test_commerce_fields.py"]
TEXT = ["tests/test_commerce_text.py", "tests/test_commerce_tools.py"]
CHECKS = ["tests/test_commerce_checks.py", "tests/test_flow_merchants.py"]
FLOW = ["tests/test_flow_merchants.py", "tests/test_flow_merchants_races.py", "tests/test_commerce_tools.py"]
SCHEMA = ["tests/test_commerce_migration.py"]
CONFIG = ["tests/test_config.py", "tests/test_commerce_tools.py"]
COMMERCE = f"{SRC}/commerce"
MIGRATION = "migrations/0020_commerce.sql"


def price(name: str, find: str, replace: str, file: str = "pricing.py") -> Mutation:
    return Mutation(f"commerce prices: {name}", f"{COMMERCE}/{file}", find, replace, PRICING)


def flow(name: str, file: str, find: str, replace: str, tests: list[str] | None = None) -> Mutation:
    return Mutation(f"commerce flow: {name}", f"{SRC}/flows/{file}", find, replace, tests or FLOW)


def bound(term: str, source: str) -> Mutation:
    """The digest the approval is bound to stops holding one of its terms."""
    return Mutation(
        f"commerce approval: the digest holds the quote's {term}",
        f"{COMMERCE}/binding.py",
        f'        "{term}": {source},',
        f'        "{term}": None,',
        FLOW,
    )


def schema(name: str, find: str, replace: str) -> Mutation:
    return Mutation(f"commerce schema: {name}", MIGRATION, find, replace, SCHEMA)


MUTATIONS: list[Mutation] = [
    *(
        bound(term, source)
        for term, source in (
            ("merchant", 'd["merchantId"]'),
            ("lines", 'd["lines"]'),
            ("fees", 'd["fees"]'),
            ("fields", 'd["fields"]'),
            ("holder", 'd["holder"]'),
            ("total", "quote.amount_kobo"),
            ("expires", "quote.expires_at"),
        )
    ),
    price(
        "an amount is refused for an offer with a price",
        "    if basket.amount_kobo is not None and not priced_by_amount:",
        "    if False:",
    ),
    price(
        "an open or ranged amount stays within the limits",
        "    if least is None or most is None or not least <= amount <= most:",
        "    if least is None or most is None:",
    ),
    price(
        "an open or ranged offer takes an amount",
        '    if amount is None:\n        raise DomainError(\n            "AMOUNT_REQUIRED"',
        '    if False:\n        raise DomainError(\n            "AMOUNT_REQUIRED"',
    ),
    price(
        "an open or ranged offer stands alone in its basket",
        "    if priced_by_amount and len(lines) > 1:",
        "    if False:",
    ),
    price("an order is at least the merchant's least", "    if total < merchant.min_kobo:", "    if False:"),
    price("an order is at most the merchant's most", "    if total > merchant.max_kobo:", "    if False:"),
    price("a sold-out offer is never priced", "    if not offer.available:", "    if False:"),
    price(
        "a count is a whole number of one to ten",
        "    return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= MAX_QUANTITY",
        "    return isinstance(value, int)",
    ),
    price("an offer has its own most", "    if line.quantity > offer.max_quantity:", "    if False:"),
    price(
        "an offer's price is its own, with its options",
        "        unit = (offer.price_kobo or 0) + sum(choice.delta_kobo for choice in picked)",
        "        unit = offer.price_kobo or 0",
    ),
    price(
        "a basket has at most twelve different items",
        "    if not counts or len(counts) > MAX_LINES:",
        "    if not counts:",
    ),
    price(
        "an option is one the offer lists",
        "        if found is None:",
        "        if False:",
        "options.py",
    ),
    price(
        "an option group takes as many as it allows",
        "        if not group.least <= counts[group.id] <= group.most:",
        "        if False:",
        "options.py",
    ),
    price(
        "a merchant that checks accounts is never quoted without a check",
        "        if merchant.checks_account != (check is not None):",
        "        if False:",
        "directory.py",
    ),
    price(
        "a merchant that does not check accounts is not asked to",
        "        if not merchant.checks_account:",
        "        if False:",
        "directory.py",
    ),
    Mutation(
        "commerce fields: a choice is one of the merchant's options",
        f"{COMMERCE}/fields.py",
        '    if found is None:\n        raise DomainError("FIELD_INVALID", f"{spec.label} must be one of',
        '    if False:\n        raise DomainError("FIELD_INVALID", f"{spec.label} must be one of',
        FIELDS,
    ),
    Mutation(
        "commerce fields: a field the merchant does not ask for is refused",
        f"{COMMERCE}/fields.py",
        "    if unknown:",
        "    if False:",
        FIELDS,
    ),
    Mutation(
        "commerce fields: a required field is asked for",
        f"{COMMERCE}/fields.py",
        "            if spec.required:",
        "            if False:",
        FIELDS,
    ),
    Mutation(
        "commerce words: a merchant's words lose their control and formatting characters",
        f"{COMMERCE}/text.py",
        '    return "" if category.startswith("C") else char',
        "    return char",
        TEXT,
    ),
    Mutation(
        "commerce words: a merchant's words keep to their length",
        f"{COMMERCE}/text.py",
        "    return line if len(line) <= limit else",
        "    return line if True else",
        TEXT,
    ),
    Mutation(
        "commerce words: the list of merchants the model reads says the names are data",
        f"{COMMERCE}/listing.py",
        '    return "\\n".join([NOTICE, *none, *table,',
        '    return "\\n".join([*none, *table,',
        TEXT,
    ),
    Mutation(
        "commerce words: the list of offers the model reads says the names are data",
        f"{COMMERCE}/listing.py",
        "    lines = [NOTICE, *none, head,",
        "    lines = [*none, head,",
        TEXT,
    ),
    Mutation(
        "commerce words: a merchant that cannot be quoted says so in its line",
        f"{COMMERCE}/listing.py",
        "    if merchant.requires_link:",
        "    if False:",
        TEXT,
    ),
    Mutation(
        "commerce: a merchant that no provider lists is refused, so a quote never names one in words",
        f"{COMMERCE}/registry.py",
        "            if found is not None:",
        "            if True:",
        FLOW + PRICING,
    ),
    Mutation(
        "commerce: a provider serves only its own merchants",
        f"{COMMERCE}/directory_store.py",
        '"SELECT * FROM merchant WHERE id = ? AND provider = ?", merchant_id, self._provider',
        '"SELECT * FROM merchant WHERE id = ? AND ? IS NOT NULL", merchant_id, self._provider',
        PRICING,
    ),
    flow(
        "a merchant that is linked or not yet live is not quoted",
        "merchants.py",
        "    if merchant.requires_link:",
        "    if False:",
    ),
    flow(
        "a merchant that is coming soon is not quoted",
        "merchants.py",
        "    if not merchant.quotable:",
        "    if False:",
    ),
    flow(
        "an amount is checked against the person's words",
        "merchants.py",
        "    confirm_stated_amount(amount_kobo, as_user_said)",
        "    pass",
    ),
    flow(
        "an amount comes with the person's words",
        "merchants.py",
        "    if not as_user_said:",
        "    if False:",
    ),
    flow(
        "the quote's own approval token is not enough: it is bound to a digest of the quote",
        "merchants.py",
        "        return quote is not None and "
        "self.ctx.ledger.check_approval_token(approval_subject(quote), token)",
        "        return quote is not None and self.ctx.ledger.check_approval_token(quote.id, token)",
    ),
    flow(
        "the token the card is given is bound to a digest of the quote",
        "merchants.py",
        "        return self.ctx.ledger.approval_token(approval_subject(quote))",
        "        return self.ctx.ledger.approval_token(quote.id)",
    ),
    flow(
        "the same key for another request is a conflict, not another quote",
        "merchants.py",
        "        fields=sorted(basket.fields.items()),",
        "        fields=[],",
    ),
    flow(
        "the check a quote carries is the one the person confirmed",
        "merchants.py",
        "        if merchant.checks_account:\n",
        "        if False:\n",
    ),
    flow(
        "an amount without lines is for a merchant's one offer paid for any amount",
        "merchants.py",
        "        if len(open_offers) != 1:",
        "        if False:",
    ),
    flow(
        "no lines and no amount is not a quote",
        "merchants.py",
        '        if amount_kobo is None:\n            raise DomainError("INVALID_INPUT", "Pass lines',
        '        if False:\n            raise DomainError("INVALID_INPUT", "Pass lines',
    ),
    flow(
        "an order is placed by one caller at a time",
        "merchant_leg.py",
        "    if not await ledger.acquire_step(quote.id, STEP_STALE_MS):",
        "    if False:",
    ),
    flow(
        "an order is placed once and asked about after that",
        "merchant_leg.py",
        '    if fulfilment["attempts"] == 0:',
        "    if True:",
    ),
    flow(
        "a merchant that refuses leaves a refund owed",
        "merchant_leg.py",
        '            case "failed" | "reversed":',
        '            case "reversed":',
    ),
    flow(
        "a pending answer is written only while the quote is approved",
        "merchant_leg.py",
        '                return await ledger.patch_progress(quote.id, patch, only_state="approved")',
        "                return await ledger.patch_progress(quote.id, patch)",
    ),
    flow(
        "a delivered answer settles an approved quote only",
        "merchant_leg.py",
        '                return await ledger.transition(quote.id, ("approved",), "settled", patch)',
        "                return await ledger.transition("
        'quote.id, ("approved", "refund_due"), "settled", patch)',
    ),
    flow(
        "a wallet-paid order a merchant refused is refunded to the wallet",
        "merchants.py",
        "        return await self.present(await refund_to_wallet(self.ctx, quote))",
        "        return await self.present(quote)",
    ),
    Mutation(
        "commerce flow: the wallet pays merchants' quotes",
        f"{SRC}/app.py",
        'WALLET_CONNECTORS = ("airtime", "merchants")',
        'WALLET_CONNECTORS = ("airtime",)',
        FLOW,
    ),
    Mutation(
        "commerce flow: a merchant's order is asked about again by the minute and by a callback",
        f"{SRC}/provider_hooks/rechecks.py",
        '    "merchants": MerchantsFlow,\n',
        "",
        FLOW,
    ),
    Mutation(
        "commerce flow: the connector reports with its own status tool",
        f"{SRC}/connectors/merchants.py",
        'kit = CardConnector(NAME, "Merchants", ctx, flow, card_html, status_name=STATUS_TOOL)',
        'kit = CardConnector(NAME, "Merchants", ctx, flow, card_html)',
        FLOW,
    ),
    Mutation(
        "commerce flow: the model's lines name an offer, a count and options and never a price",
        f"{SRC}/connectors/merchants.py",
        "class QuoteLine(Strict):",
        'class QuoteLine(Strict, extra="allow"):',
        FLOW,
    ),
    Mutation(
        "commerce flow: the quote tool is read from its own arguments alone",
        f"{SRC}/connectors/merchants.py",
        "class CreateQuote(Strict):",
        'class CreateQuote(Strict, extra="allow"):',
        FLOW,
    ),
    Mutation(
        "commerce checks: an account check is the owner's own",
        f"{COMMERCE}/checks.py",
        '"SELECT * FROM account_check WHERE id = ? AND owner = ?", check_id, self._owner()',
        '"SELECT * FROM account_check WHERE id = ? AND ? IS NOT NULL", check_id, self._owner()',
        CHECKS,
    ),
    Mutation(
        "commerce checks: a check is for the merchant and details it was made for",
        f"{COMMERCE}/checks.py",
        "        if check.merchant_id != merchant.id or "
        "any(fields.get(k) != v for k, v in check.fields.items()):",
        "        if False:",
        CHECKS,
    ),
    Mutation(
        "commerce checks: a check expires",
        f"{COMMERCE}/checks.py",
        "        if check.expires_at <= self._clock.now():",
        "        if False:",
        CHECKS,
    ),
    Mutation(
        "commerce checks: a quote needs a check where the provider checks",
        f"{COMMERCE}/checks.py",
        "        if check_id is None:",
        "        if False:",
        CHECKS,
    ),
    Mutation(
        "commerce checks: the holder's words are cleaned before they are kept",
        f"{COMMERCE}/checks.py",
        "        holder, wanted = third_party(found.holder_name, HOLDER_LIMIT), canonical(fields)",
        "        holder, wanted = found.holder_name, canonical(fields)",
        CHECKS,
    ),
    Mutation(
        "commerce simulated merchants: a merchant that answered keeps its answer",
        f"{COMMERCE}/simulated.py",
        "excluded.description WHERE sim_merchant_order.outcome = 'pending'\",",
        'excluded.description",',
        FLOW,
    ),
    Mutation(
        "free text merchants: the payment tool is offered only while it is allowed",
        f"{SRC}/connectors/pay.py",
        "    return kit.build(purpose, (quote,) if ctx.free_text_merchants else ())",
        "    return kit.build(purpose, (quote,))",
        CONFIG,
    ),
    Mutation(
        "free text merchants: a quote naming a merchant in words is refused while it is off",
        f"{SRC}/flows/payment.py",
        "            if not self.ctx.free_text_merchants:",
        "            if False:",
        CONFIG,
    ),
    Mutation(
        "free text merchants: it is refused on beside a provider that is not simulated or in a sandbox",
        f"{SRC}/config.py",
        "    if wanted and not safe:",
        "    if False:",
        CONFIG,
    ),
    Mutation(
        "free text merchants: every provider must be simulated or in a sandbox",
        f"{SRC}/config.py",
        "    safe = paystack.mode in SAFE_MODES and vtpass.mode in SAFE_MODES and bachs.mode in SAFE_MODES",
        "    safe = True",
        CONFIG,
    ),
    Mutation(
        "free text merchants: it is off when nothing asked for it beside a live provider",
        f"{SRC}/config.py",
        "    wanted = safe if asked is None else asked",
        "    wanted = True if asked is None else asked",
        CONFIG,
    ),
    schema(
        "a ranged offer names both its limits",
        "AND max_kobo IS NOT NULL\n      AND max_kobo >= min_kobo)",
        "AND max_kobo >= min_kobo)",
    ),
    schema(
        "a merchant is live, beta or coming soon",
        "status TEXT NOT NULL CHECK (status IN ('live', 'beta', 'coming_soon')),",
        "status TEXT NOT NULL,",
    ),
    schema(
        "a merchant's least is below its most",
        "max_kobo INTEGER NOT NULL CHECK (typeof(max_kobo) = 'integer' AND max_kobo >= min_kobo),",
        "max_kobo INTEGER NOT NULL,",
    ),
    schema(
        "an offer allows at most ten of one",
        "CHECK (typeof(max_quantity) = 'integer' AND max_quantity BETWEEN 1 AND 10)",
        "CHECK (typeof(max_quantity) = 'integer')",
    ),
    schema(
        "a merchant keeps its id and provider",
        "BEFORE UPDATE OF id, provider ON merchant",
        "BEFORE UPDATE OF provider ON merchant",
    ),
    schema(
        "an offer keeps its merchant, id and kind of price",
        "BEFORE UPDATE OF merchant_id, id, price_kind ON offer",
        "BEFORE UPDATE OF merchant_id, id ON offer",
    ),
    schema(
        "a merchant a quote names is not removed",
        "json_extract(q.details, '$.merchantId') = OLD.id",
        "json_extract(q.details, '$.merchantId') = OLD.name",
    ),
    schema(
        "an offer a quote names is not removed",
        "AND json_extract(l.value, '$.offerId') = OLD.id",
        "AND json_extract(l.value, '$.offerId') = OLD.name",
    ),
    Mutation(
        "commerce schema: an account check cannot be changed",
        "migrations/0022_index.sql",
        "BEFORE UPDATE ON account_check",
        "BEFORE UPDATE OF created_at ON account_check",
        SCHEMA,
    ),
    schema("a merchant that answered keeps its answer", "WHEN OLD.outcome <> 'pending'", "WHEN 0"),
]
