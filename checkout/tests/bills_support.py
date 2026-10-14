# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared by the bills tests: television and electricity quoted from the simulated VTpass through the
`merchants` connector, with the smartcard and the meters VTpass's documentation gives its sandbox."""

from typing import Any

from checkout.commerce.vtpass_provider import VtpassProvider
from checkout.vtpass.bills import BillAccount
from tests.commerce_support import CONNECTOR, approval, as_account, fund, new_key, stored
from tests.connector_support import quote_of, text_of
from tests.support import ALICE, Stack

SMARTCARD = "1212121212"
PREPAID = "1111111111111"
POSTPAID = "1010101010101"
PENDING = "201000000000"
UNEXPECTED = "500000000000"
SILENT = "400000000000"
TIMEOUT = "300000000000"
FAILING = "100000000000"
WRONG = "9999999999999"
PHONE = "08031234567"
RENEWAL_KOBO = 1_050_000
FIVE_THOUSAND = 500_000


async def check(stack: Stack, merchant: str, account: str, meter_type: str | None = None, **over: Any):
    """`check_account` for a bill, as a signed-in account does."""
    fields = {("smartcard" if merchant in ("dstv", "gotv", "startimes") else "meter_number"): account}
    if meter_type:
        fields["meter_type"] = meter_type
    return await as_account(stack, "check_account", merchant_id=merchant, fields=fields, **over)


async def check_id(stack: Stack, merchant: str, account: str, meter_type: str | None = None) -> str:
    result = await check(stack, merchant, account, meter_type)
    assert "isError" not in result, text_of(result)
    return result["structuredContent"]["check_id"]


def renewal(check: str, **over: Any) -> dict[str, Any]:
    """A DStv renewal of the card's current bouquet, quoted at the amount the check gave."""
    return {
        "merchant_id": "dstv",
        "lines": [{"offer_id": "renew"}],
        "fields": {"smartcard": SMARTCARD, "phone": PHONE},
        "check_id": check,
        "idempotency_key": new_key(),
        **over,
    }


def electricity(
    check: str, account: str = PREPAID, meter_type: str = "prepaid", **over: Any
) -> dict[str, Any]:
    """Five thousand naira of electricity from Ikeja Electric."""
    return {
        "merchant_id": "ikeja-electric",
        "lines": [{"offer_id": "electricity"}],
        "amount_kobo": FIVE_THOUSAND,
        "amount_as_user_said": "5000",
        "fields": {"meter_number": account, "meter_type": meter_type, "phone": PHONE},
        "check_id": check,
        "idempotency_key": new_key(),
        **over,
    }


async def renewal_quote(stack: Stack, card: str = SMARTCARD, **over: Any) -> dict[str, Any]:
    fields = {"smartcard": card, "phone": PHONE}
    ck = await check_id(stack, "dstv", card)
    made = await as_account(stack, "create_quote", **renewal(ck, **{"fields": fields, **over}))
    assert "isError" not in made, text_of(made)
    return made


async def electricity_quote(
    stack: Stack, account: str = PREPAID, meter_type: str = "prepaid", **over: Any
) -> dict[str, Any]:
    ck = await check_id(stack, "ikeja-electric", account, meter_type)
    made = await as_account(stack, "create_quote", **electricity(ck, account, meter_type, **over))
    assert "isError" not in made, text_of(made)
    return made


async def pay_from_wallet(stack: Stack, made: dict[str, Any], owner: str = ALICE) -> dict[str, Any]:
    """The quote approved on the card with the wallet, funded first: the card's view after the approval."""
    await fund(stack, 10_000_000, owner, ref=f"top-up-{quote_of(made)['id']}")
    done = await as_account(stack, "approve_quote", **approval(made, funding="wallet"))
    assert "isError" not in done, text_of(done)
    return quote_of(done)


async def pay_at_checkout(stack: Stack, made: dict[str, Any]) -> dict[str, Any]:
    """The quote approved for the checkout and paid on the simulated page: the card's view after the check."""
    approved = await as_account(stack, "approve_quote", **approval(made))
    assert "isError" not in approved, text_of(approved)
    await stack.complete_checkout(quote_of(approved)["checkoutUrl"], "success")
    return quote_of(await as_account(stack, "verify_quote", quote_id=quote_of(made)["id"]))


async def phase_of(stack: Stack, quote_id: str) -> str:
    return quote_of(await as_account(stack, "verify_quote", quote_id=quote_id))["phase"]


async def state_of(stack: Stack, quote_id: str) -> str:
    return (await stored(stack, quote_id))["state"]


class VtpassOverride:
    """The VTpass client with some calls replaced, and every call counted."""

    def __init__(self, inner, **replacements) -> None:
        self._inner, self._replacements = inner, replacements
        self.calls: dict[str, int] = {}

    def __getattr__(self, name):
        self.calls.setdefault(name, 0)
        target = self._replacements.get(name) or getattr(self._inner, name)

        async def called(*args, **kwargs):
            self.calls[name] += 1
            return await target(*args, **kwargs)

        return called


def bills(stack: Stack) -> VtpassProvider:
    provider = stack.app.contexts[CONNECTOR].providers.named("vtpass")
    assert isinstance(provider, VtpassProvider)
    return provider


def use_api(stack: Stack, **replacements) -> VtpassOverride:
    """Puts an override between the bills provider and VTpass: some calls answer as the test says."""
    provider = bills(stack)
    override = VtpassOverride(provider._api, **replacements)
    provider._api = override
    return override


def knows(account: BillAccount):
    """A `verify_bill` that finds this account whatever number it is asked for."""

    async def verify_bill(_check):
        return account

    return verify_bill
