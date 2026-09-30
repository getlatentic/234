# SPDX-License-Identifier: AGPL-3.0-or-later
"""Exercises the real Paystack test API and the VTpass sandbox with the keys the owner provides.

It refuses live keys (exit 2), prints nothing secret, calls only Paystack test mode and the VTpass
sandbox, and exits 3 if it had no keys to check with. With no keys it checks nothing: it says so and stops.

    tools/live-check.sh                 every check that has keys
    tools/live-check.sh --no-transfer   skip the transfer checks
    tools/live-check.sh --pay           also wait while you pay a real test checkout
                                        (card 4084 0840 8408 4081, any future expiry, CVV 408)
    tools/live-check.sh --self-test     the same checks against the simulators: proves this script, not
                                        the real APIs
    tools/live-check.sh --env-file F    read KEY=VALUE lines from F, then the environment

The keys are read from the environment (or the file named by --env-file), never from the repository.
"""

import argparse
import asyncio
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from checkout.app import SIMULATED_KEY, SIMULATED_VTPASS
from checkout.clock import Clock, SystemClock
from checkout.config import Settings
from checkout.errors import ConfigError
from checkout.paystack.api import PaystackApi
from checkout.paystack.client import PaystackClient
from checkout.paystack.sim import PaystackSimulator
from checkout.paystack.sim_store import PaystackSimStore
from checkout.sqlite_db import SqliteDb
from checkout.transport import Transport
from checkout.vtpass.api import VtpassApi
from checkout.vtpass.client import VtpassClient
from checkout.vtpass.sim import VtpassSimulator
from checkout.vtpass.sim_store import VtpassSimStore
from tools.live_paystack import paystack_checks
from tools.live_report import Report
from tools.live_transport import UrllibTransport
from tools.live_vtpass import vtpass_checks


@dataclass
class Targets:
    paystack: PaystackApi | None
    vtpass: VtpassApi | None
    email: str


def simulated_targets(settings: Settings, clock: Clock) -> Targets:
    db = SqliteDb()
    sim = settings.simulator
    simulator = PaystackSimulator(
        PaystackSimStore(db),
        "http://localhost/sim/checkout",
        transfer_otp=sim.transfer_otp,
        payouts_refused=sim.payouts_refused,
    )
    vtpass = VtpassClient(
        SIMULATED_VTPASS,
        VtpassSimulator(VtpassSimStore(db), clock, reject_credentials=sim.vtpass_rejects_credentials),
        clock=clock,
    )
    return Targets(PaystackClient(SIMULATED_KEY, simulator), vtpass, settings.payer_email)


def real_targets(settings: Settings, report: Report, transport: Transport) -> Targets:
    key = settings.paystack.secret_key
    paystack = PaystackClient(key, transport) if key else None
    credentials = settings.vtpass.credentials
    debug = (lambda line: print(line, file=sys.stderr)) if settings.vtpass.debug else None
    vtpass = VtpassClient(credentials, transport, debug=debug) if credentials else None
    if paystack is None:
        report.note("Paystack", "skipped: no PAYSTACK_TEST_SECRET_KEY set, or PAYSTACK_MODE=simulated.")
    if vtpass is None:
        report.note(
            "VTpass",
            "skipped: no VTPASS_API_KEY, VTPASS_PUBLIC_KEY and VTPASS_SECRET_KEY set, or "
            "VTPASS_MODE=simulated.",
        )
    return Targets(paystack, vtpass, settings.payer_email)


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        text = line.strip()
        if text and not text.startswith("#") and "=" in text:
            name, value = text.split("=", 1)
            values[name.strip()] = value.strip().strip("'\"")
    return values


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="live_check", description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--no-transfer", action="store_true")
    parser.add_argument("--pay", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--env-file", type=Path)
    return parser.parse_args(argv)


async def run(
    argv: list[str],
    environ: Mapping[str, str],
    clock: Clock | None = None,
    transport: Transport | None = None,
) -> int:
    args = parse_args(argv)
    report = Report()
    env = {**(read_env_file(args.env_file) if args.env_file else {}), **environ}
    try:
        settings = Settings.from_env({"APPROVAL_SECRET": "live-check-not-a-secret", **env}.get)
    except ConfigError as error:
        report.say(f"Refused to run: {error.message}")
        return 2
    if args.self_test:
        report.say(
            "SELF-TEST: these checks run against the simulators. They prove this script, not the real APIs."
        )
        targets = simulated_targets(settings, clock or SystemClock())
    else:
        targets = real_targets(settings, report, transport or UrllibTransport())
    if targets.paystack:
        report.say(
            "\nPaystack (simulated)" if args.self_test else "\nPaystack test mode (no real money moves)"
        )
        await paystack_checks(
            targets.paystack, report, real_host=not args.self_test, email=targets.email,
            transfer=not args.no_transfer, pay=args.pay and not args.self_test,
        )  # fmt: skip
    if targets.vtpass:
        await vtpass_checks(targets.vtpass, report, simulated=args.self_test)
    report.say(f"\n{report.ok} passed, {report.failed} failed, {report.notes} notes.")
    if report.ok + report.failed == 0:
        report.say("Nothing was checked. Set the test keys (see the README's section on real test mode).")
        return 3
    return 0 if report.failed == 0 else 1


def main() -> None:
    sys.exit(asyncio.run(run(sys.argv[1:], os.environ)))


if __name__ == "__main__":
    main()
