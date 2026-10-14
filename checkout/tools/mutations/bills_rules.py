# SPDX-License-Identifier: AGPL-3.0-or-later
"""The rules of television and electricity through VTpass (docs/commerce.md, "Providers";
commerce/vtpass_*.py, vtpass/bills.py, vtpass/receipt.py, flows/merchant_leg.py, flows/reversal.py): bills
are offered only while VTpass is simulated or in its sandbox; a smartcard or meter VTpass does not know,
or cannot sell to, is refused and never quoted; a price is VTpass's list price, the check's renewal
amount, or an amount within the check's limits, and never the model's; the order is placed once under the
quote's request id for the bill alone; a token reaches the receipt; and an order VTpass takes back after
delivery is reversed and refunded."""

from tools.mutations.model import SRC, Mutation

COMMERCE = f"{SRC}/commerce"
VTPASS = f"{SRC}/vtpass"
SIM = ["tests/test_vtpass_bills.py", "tests/test_vtpass_bills_sim.py"]
QUOTES = ["tests/test_bills_quotes.py", "tests/test_bills_provider.py"]
FLOW = ["tests/test_flow_bills.py", "tests/test_flow_bills_races.py"]
CONFIG = ["tests/test_bills_config.py"]


def bills(name: str, file: str, find: str, replace: str, tests: list[str]) -> Mutation:
    return Mutation(f"bills: {name}", file, find, replace, tests)


def provider(name: str, find: str, replace: str, tests: list[str] | None = None) -> Mutation:
    return bills(name, f"{COMMERCE}/vtpass_provider.py", find, replace, tests or FLOW + CONFIG)


def price(name: str, find: str, replace: str) -> Mutation:
    return bills(name, f"{COMMERCE}/vtpass_price.py", find, replace, QUOTES)


def refusal(name: str, find: str) -> Mutation:
    """VTpass's account check stops refusing one kind of number."""
    return bills(name, f"{VTPASS}/bills.py", find, "    if False:", SIM + QUOTES)


MUTATIONS: list[Mutation] = [
    provider(
        "bills are offered only while VTpass is simulated or in its sandbox",
        "mode in OFFERED_MODES else ()",
        "True else ()",
        CONFIG,
    ),
    provider(
        "the provider cannot be built for another mode",
        "        if mode not in OFFERED_MODES:",
        "        if False:",
        CONFIG,
    ),
    refusal(
        "a number VTpass calls a wrong biller code is refused",
        '    if content.get("WrongBillersCode") not in _WRONG:',
    ),
    refusal("a number VTpass could not verify is refused", '    if content.get("error"):'),
    refusal(
        "a meter VTpass cannot sell to is refused",
        "    if can_vend is not None and str(can_vend).strip().lower() in _CANNOT_VEND:",
    ),
    refusal("an account with no holder is refused", '    if _text(content, "Customer_Name") is None:'),
    bills(
        "a refused account is reported as not found, with nothing quoted",
        f"{COMMERCE}/vtpass_check.py",
        "    except BillRefused as error:",
        "    except ZeroDivisionError as error:",
        QUOTES,
    ),
    bills(
        "the account check keeps what the quote prices from",
        f"{SRC}/commerce/checks.py",
        "        detail = canonical(stored)",
        '        detail = "{}"',
        QUOTES,
    ),
    bills(
        "an account check takes the fields that name the account and no others",
        f"{COMMERCE}/model.py",
        "spec.account) or self.fields",
        "spec.account) and self.fields",
        QUOTES,
    ),
    price(
        "a quote needs an account check where the merchant checks accounts",
        "    if merchant.checks_account != (check is not None):",
        "    if False:",
    ),
    price("a quote is one subscription or purchase", "    if len(basket.lines) != 1:", "    if False:"),
    price(
        "the phone is written nationally",
        '    phone = normalise_phone(basket.fields["phone"])',
        '    phone = basket.fields["phone"]',
    ),
    price(
        "a renewal costs the amount the check gave",
        'PricedLine(offer.id, f"Renew {bouquet}" if bouquet else offer.name, 1, renewal)',
        'PricedLine(offer.id, f"Renew {bouquet}" if bouquet else offer.name, 1, 100_000)',
    ),
    price("a renewal VTpass gave no amount for is refused", "    if not renewal:", "    if False:"),
    price(
        "a renewal takes no amount from the model",
        "        if basket.amount_kobo is not None:",
        "        if False:",
    ),
    price("a change of bouquet says it is one", 'f"Change to {x.name}"', "x.name"),
    price("an amount below the meter's least is refused", "(least and amount < least) or ", ""),
    price("an amount above the meter's most is refused", " or (most and amount > most)", ""),
    price(
        "the service fee is a line of its own",
        "    fees = (Fee(SERVICE_FEE, fee_kobo),) if fee_kobo else ()",
        "    fees = ()",
    ),
    provider(
        "nothing is quoted for a VTpass that will not take orders",
        "        if not access.ok:",
        "        if False:",
        QUOTES + FLOW,
    ),
    provider(
        "nothing is quoted for a VTpass wallet that cannot cover it",
        "        if access.balance_kobo is not None and access.balance_kobo < amount_kobo:",
        "        if False:",
        QUOTES + FLOW,
    ),
    provider(
        "VTpass is ordered the bill alone, not the service fee",
        'amount_kobo=quote.details["subtotalKobo"],',
        "amount_kobo=quote.amount_kobo,",
    ),
    provider(
        "the request id is the Lagos minute then the quote",
        "return request_id_at(now, quote.id)",
        "return quote.id",
    ),
    provider(
        "a reversal is its own outcome",
        'status = "reversed" if reply.reversed else reply.status',
        "status = reply.status",
    ),
    bills(
        "a request VTpass never saw is ordered again under the same id",
        f"{SRC}/flows/merchant_leg.py",
        "if outcome.unknown_request else outcome",
        "if False else outcome",
        FLOW,
    ),
    bills(
        "what a delivered bill gave is kept with the order",
        f"{SRC}/flows/merchant_leg.py",
        "} if outcome.receipt else {}),",
        "} if False else {}),",
        FLOW,
    ),
    bills(
        "a purchased code that is not a token is not shown as one",
        f"{VTPASS}/receipt.py",
        '    elif not _clean(payload.get("token")):',
        "    elif False:",
        SIM,
    ),
    bills(
        "a delivered bill says what it gave in words",
        f"{SRC}/present.py",
        '    if phase == "succeeded":\n        return _delivered_message(quote)',
        '    if phase == "succeeded":\n        return None',
        FLOW,
    ),
    bills(
        "a subscription's receipt says how long it lasts",
        f"{SRC}/receipts.py",
        "if months else []",
        "if False else []",
        FLOW,
    ),
    bills(
        "the approval is bound to what will be ordered",
        f"{COMMERCE}/binding.py",
        '        "order": d.get("order"),',
        '        "order": None,',
        QUOTES,
    ),
    bills(
        "a bill is shown as VTpass's and no shop's",
        f"{SRC}/present.py",
        'quote.details.get("provider") == "vtpass"',
        'quote.details.get("provider") == "directory"',
        FLOW,
    ),
    bills(
        "a delivered bill can be reversed through the merchants connector",
        f"{SRC}/provider_hooks/rechecks.py",
        'row["state"] == "settled" and row["connector"] in REVERSIBLE',
        'row["state"] == "settled" and row["connector"] == "airtime"',
        FLOW,
    ),
    bills(
        "a quote for a checked account takes the account from its check",
        f"{SRC}/flows/merchants.py",
        "checked = await self.checks.fields_of(check_id) if merchant.checks_account else {}",
        "checked = {}",
        QUOTES,
    ),
    bills(
        "only the owner's own check lends its fields",
        f"{COMMERCE}/checks.py",
        '"SELECT fields, detail FROM account_check WHERE id = ? AND owner = ?"',
        '"SELECT fields, detail FROM account_check WHERE id = ? AND ? IS NOT NULL"',
        QUOTES,
    ),
    bills(
        "the phone given with a check is kept for the quote",
        f"{SRC}/connectors/merchants.py",
        "checks.record(merchant, fields, found, carried_fields(merchant, args.fields))",
        "checks.record(merchant, fields, found, {})",
        QUOTES,
    ),
    bills(
        "a service fee is a whole number of kobo",
        f"{SRC}/config.py",
        "        if not raw.isdecimal():\n            raise ConfigError(f'{name} must be a whole",
        "        if False:\n            raise ConfigError(f'{name} must be a whole",
        CONFIG,
    ),
]
