# SPDX-License-Identifier: AGPL-3.0-or-later
"""The VTpass sandbox checks: plans, the balance as a credentials check, the documented scenarios."""

import time

from checkout.vtpass.api import AirtimeOrder, VtpassApi
from tools.live_paystack import stamp
from tools.live_report import Report


def _order_id(suffix: str) -> str:
    lagos = time.gmtime(time.time() + 3600)
    return f"{time.strftime('%Y%m%d%H%M', lagos)}{suffix}{stamp()}"


SANDBOX_FAILING_NUMBER = "08031234567"
SIMULATOR_FAILING_NUMBER = "100000000000"


async def vtpass_checks(vtpass: VtpassApi, report: Report, *, simulated: bool = False) -> None:
    """The simulator delivers to any valid number, so its self-test fails the number it keeps for failure."""
    report.say("\nVTpass sandbox (sandbox.vtpass.com)")
    await report.check(
        "list MTN data plans (needs no credentials, so it proves nothing about them)",
        lambda: vtpass.data_plans("mtn"),
        lambda plans: None if plans else "no plans",
    )
    if not await access_check(vtpass, report):
        return

    def order(suffix: str, phone: str) -> AirtimeOrder:
        return AirtimeOrder(_order_id(suffix), "mtn", phone, 10_000)

    def status_is(expected: str):
        return lambda o: None if o.status == expected else f"{o.status}: {o.description}"

    success = order("ok", "08011111111")
    await report.check(
        "airtime to the success number 08011111111",
        lambda: vtpass.buy_airtime(success),
        status_is("delivered"),
    )
    await report.check(
        "requery that order", lambda: vtpass.requery(success.request_id), status_is("delivered")
    )
    fail = order("no", SIMULATOR_FAILING_NUMBER if simulated else SANDBOX_FAILING_NUMBER)
    await report.check(
        "airtime to a failing number fails" + ("" if simulated else ", as the sandbox documents"),
        lambda: vtpass.buy_airtime(fail),
        status_is("failed"),
    )
    pending = order("pe", "201000000000")
    await report.check(
        "airtime to the pending number stays pending",
        lambda: vtpass.buy_airtime(pending),
        status_is("pending"),
    )
    await report.check(
        "requery of an unknown request id",
        lambda: vtpass.requery(_order_id("xx")),
        lambda o: None if o.unknown_request else f"{o.status}: code {o.code or 'none'}",
    )


async def access_check(vtpass: VtpassApi, report: Report) -> bool:
    """Purchases and the balance need valid credentials; if VTpass refuses them the purchase checks would
    only repeat that."""
    access = await vtpass.check_access()
    if access.ok:
        wallet = (
            ""
            if access.balance_kobo is None
            else f"₦{round(access.balance_kobo / 100)} in the sandbox wallet"
        )
        report.passed("VTpass accepts the credentials (wallet balance)", wallet)
        return True
    report.failure(
        "VTpass accepts the credentials (wallet balance)",
        f"{access.reason} Fix on the owner's side: sandbox.vtpass.com profile, API Keys tab, set API "
        'AUTHENTICATION TYPE to "all" or API keys, and check the VTPASS_* values; also tick the products to '
        "sell on the Product Settings tab. The purchase checks are skipped.",
    )
    return False
