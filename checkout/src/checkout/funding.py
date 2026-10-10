# SPDX-License-Identifier: AGPL-3.0-or-later
"""Wiring for the wallet's top-ups: the Bachs they are paid on (the real client over the network in
sandbox mode, over the simulator otherwise), the secrets a webhook must be signed with, and the /hooks/bachs
handler."""

from dataclasses import dataclass

from .audit import Audit
from .bachs.api import BachsApi
from .bachs.client import BachsClient
from .bachs.sim import SIMULATED_KEY, BachsSimulator, simulated_webhook_secret
from .bachs.sim_store import BachsSimStore
from .clock import Clock
from .config import Settings
from .db import Db
from .provider_hooks.bachs import BachsHook
from .transport import Transport
from .wallet.journal import Journal
from .wallet.topup_credit import TopUpCredit
from .wallet.topups import CheckoutTerms, TopUps


@dataclass(frozen=True)
class Funding:
    topups: TopUps
    hook: BachsHook
    sim: BachsSimStore | None
    """The simulator's checkouts, for its pay page; None when top-ups are paid on the real sandbox."""


def _bachs_for(
    settings: Settings, db: Db, clock: Clock, transport: Transport
) -> tuple[BachsApi, tuple[str, ...], BachsSimStore | None]:
    bachs = settings.bachs
    if bachs.mode == "sandbox" and bachs.secret_key and bachs.webhook_secret:
        return BachsClient(bachs.secret_key, transport, base_url=bachs.api_url), (bachs.webhook_secret,), None
    store = BachsSimStore(db)
    page = f"{settings.public_base_url.rstrip('/')}/sim/bachs"
    simulated = BachsClient(SIMULATED_KEY, BachsSimulator(store, clock, page))
    return simulated, (simulated_webhook_secret(settings.approval_secret),), store


def build_funding(settings: Settings, db: Db, clock: Clock, audit: Audit, transport: Transport) -> Funding:
    bachs, secrets, sim = _bachs_for(settings, db, clock, transport)
    # Bachs takes only a public https address to send the payer back to.
    back = settings.host_public_url if (settings.host_public_url or "").startswith("https://") else None
    topups = TopUps(
        db, clock, Journal(db, clock, settings.wallet), bachs, CheckoutTerms(settings.payer_email, back)
    )
    audit.log("bachs.startup", mode="simulated" if sim else "sandbox")
    return Funding(topups, BachsHook(TopUpCredit(topups, db, clock, audit), secrets, clock, audit), sim)
