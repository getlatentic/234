# SPDX-License-Identifier: AGPL-3.0-or-later
"""Wiring: the four payment connectors and memory, built from configuration a Worker (or a test) provides.

Every connector shares one ledger, so each owner has one daily limit across all of them. Each connector has
its own Paystack mode, and the airtime connector has a VTpass mode; both run the real client, over the real
network in test/sandbox mode and over a simulator otherwise.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .audit import Audit, print_sink
from .background import Background, build_background
from .clock import Clock, SystemClock
from .config import CONNECTORS, Settings
from .connectors import airtime, food_order, pay, send_money
from .connectors import knowledge as knowledge_connector
from .connectors import memory as memory_connector
from .connectors import web as web_connector
from .connectors.kit import CardReader
from .connectors.web import WebSearch
from .db import Db
from .errors import ConfigError
from .flows.context import Context
from .jobs import HeldJobs
from .knowledge.store import KnowledgeStore
from .ledger import Ledger, Limits
from .mcp.registry import Connector
from .memory.context import MemoryContext
from .memory.proposals import Proposals
from .memory.store import MemoryStore
from .modes import Modes
from .owner import DEFAULT_OWNER
from .paystack.api import PaystackApi
from .paystack.client import PaystackClient
from .paystack.sim import PaystackSimulator
from .paystack.sim_store import PaystackSimStore
from .transport import Transport, WorkerFetch
from .vtpass.api import VtpassApi
from .vtpass.client import VtpassClient, VtpassCredentials
from .vtpass.sim import VtpassSimulator
from .vtpass.sim_store import VtpassSimStore
from .wallet.journal import Journal
from .wallet.spending import WalletSpending
from .web.cache import WebCache
from .web.fetcher import Fetcher, WorkerPageFetch
from .web.reader import Policy, WebReader
from .web.search import GatewaySearch
from .web.search_budget import SearchBudget

CARD_DIR = Path(__file__).parent / "card"
MENU_FILE = "menu.html"
MEMORY_CARD_FILE = "memory.html"
SIMULATED_KEY = "sk_test_simulated"
SIMULATED_VTPASS = VtpassCredentials("simulated", "simulated", "simulated")
FOOD_MERCHANT = "Simulated merchant: not Chowdeck"
PAYOUTS_REASON = "this Paystack account cannot make payouts"


@dataclass(frozen=True)
class App:
    settings: Settings
    db: Db
    clock: Clock
    ledger: Ledger
    paystack_sim: PaystackSimStore
    contexts: Mapping[str, Context]
    connectors: Mapping[str, Connector]
    background: Background


def card_reader(name: str) -> CardReader:
    async def read() -> str:
        return (CARD_DIR / name).read_text(encoding="utf-8")

    return read


def _paystack_for(
    settings: Settings, db: Db, connector: str, transport: Transport
) -> tuple[PaystackApi, str]:
    mode = settings.paystack.mode_for(connector)
    if mode == "test":
        if settings.paystack.secret_key is None:
            raise ConfigError(
                "Real Paystack test mode needs PAYSTACK_TEST_SECRET_KEY set to an sk_test_ key."
            )
        return PaystackClient(
            settings.paystack.secret_key, transport, base_url=settings.paystack.api_url
        ), mode
    sim = settings.simulator
    checkout = f"{settings.public_base_url.rstrip('/')}/sim/checkout"
    simulator = PaystackSimulator(
        PaystackSimStore(db), checkout, transfer_otp=sim.transfer_otp, payouts_refused=sim.payouts_refused
    )
    return PaystackClient(SIMULATED_KEY, simulator), "simulated"


def _vtpass_for(
    settings: Settings, db: Db, clock: Clock, audit: Audit, transport: Transport
) -> tuple[VtpassApi, str]:
    vt = settings.vtpass
    if vt.mode == "sandbox" and vt.credentials is not None:
        debug = (lambda line: audit.log("vtpass.debug", line=line)) if vt.debug else None
        return VtpassClient(vt.credentials, transport, clock=clock, debug=debug), "sandbox"
    sim = settings.simulator
    simulator = VtpassSimulator(
        VtpassSimStore(db),
        clock,
        pending_seconds=sim.pending_seconds,
        reject_credentials=sim.vtpass_rejects_credentials,
    )
    return VtpassClient(SIMULATED_VTPASS, simulator, clock=clock), "simulated"


def build_contexts(
    settings: Settings, db: Db, clock: Clock, audit: Audit, transport: Transport | None = None
) -> tuple[Ledger, dict[str, Context]]:
    transport = transport or WorkerFetch()
    ledger = Ledger(
        db,
        clock,
        Limits(settings.per_payment_limit_kobo, settings.daily_limit_kobo, settings.group_daily_limit_kobo),
        settings.quote_ttl_seconds,
        settings.approval_secret,
        None if settings.require_owner else DEFAULT_OWNER,
    )
    store = MemoryStore(db, clock, settings.memory)
    wallet = WalletSpending(Journal(db, clock, settings.wallet), db, clock)
    contexts: dict[str, Context] = {}
    for connector in CONNECTORS:
        paystack, paystack_mode = _paystack_for(settings, db, connector, transport)
        vtpass, vtpass_mode = (
            _vtpass_for(settings, db, clock, audit, transport) if connector == "airtime" else (None, None)
        )
        reason = (
            PAYOUTS_REASON
            if connector == "send-money" and paystack_mode == "simulated" and settings.paystack.secret_key
            else None
        )
        modes = Modes(
            paystack_mode,
            vtpass_mode,
            FOOD_MERCHANT if connector == "food-order" else None,
            reason,
        )
        contexts[connector] = Context(
            ledger=ledger,
            paystack=paystack,
            modes=modes,
            audit=audit,
            clock=clock,
            payer_email=settings.payer_email,
            checkout_window_seconds=settings.checkout_window_seconds,
            vtpass=vtpass,
            food_step_seconds=settings.simulator.food_step_seconds,
            inline_checkout=paystack_mode == "test" and settings.inline_paystack,
            card_csp_extra=settings.card_csp_extra,
            memory=store,
            wallet=wallet if connector == "airtime" else None,
        )
        audit.log(
            "startup",
            connector=connector,
            paystack_mode=paystack_mode,
            vtpass_mode=vtpass_mode,
            per_payment_limit_kobo=settings.per_payment_limit_kobo,
            daily_limit_kobo=settings.daily_limit_kobo,
        )
    return ledger, contexts


def memory_context(
    settings: Settings, contexts: Mapping[str, Context], db: Db, clock: Clock, audit: Audit
) -> MemoryContext:
    """Memory looks accounts up through the send-money connector's Paystack, as a transfer quote does."""
    send = contexts["send-money"]
    assert send.memory is not None
    proposals = Proposals(db, clock, settings.memory, settings.approval_secret)
    return MemoryContext(send.memory, proposals, send.paystack, audit, clock)


def build_connectors(
    settings: Settings,
    contexts: Mapping[str, Context],
    memory: MemoryContext,
    knowledge: KnowledgeStore,
    reader: WebReader,
    search: WebSearch | None = None,
    clock: Clock | None = None,
) -> dict[str, Connector]:
    card = card_reader(settings.card_file)
    alternatives = {name: card_reader(file) for name, file in settings.alt_cards}
    built = (
        pay.build_connector(contexts["paystack-pay"], card, alternatives),
        send_money.build_connector(contexts["send-money"], card),
        airtime.build_connector(contexts["airtime"], card),
        food_order.build_connector(contexts["food-order"], card, card_reader(MENU_FILE)),
        memory_connector.build_connector(memory, card_reader(MEMORY_CARD_FILE)),
        knowledge_connector.build_connector(knowledge, memory.audit),
        web_connector.build_connector(reader, memory.audit, search, clock),
    )
    return {connector.name: connector for connector in built}


def web_search_for(settings: Settings, db: Db, clock: Clock, transport: Transport) -> WebSearch | None:
    """Web search, when a gateway and its key are set (web/settings.py)."""
    found = settings.web_search
    if found is None:
        return None
    moment = lambda: datetime.fromtimestamp(clock.now() / 1000, UTC)  # noqa: E731
    gateway = GatewaySearch(
        transport, found.credentials, found.gateway_url, found.target, found.region, moment
    )
    return WebSearch(gateway, SearchBudget(db, clock, found.per_day), WebCache(db, clock), clock)


def build_app(
    settings: Settings,
    db: Db,
    clock: Clock | None = None,
    audit: Audit | None = None,
    transport: Transport | None = None,
    callback_transport: Transport | None = None,
    queues: Mapping[str, Any] | None = None,
    jobs: HeldJobs | None = None,
    page_fetcher: Fetcher | None = None,
) -> App:
    """`callback_transport` reaches event subscribers (the chat host through its binding); `queues` are the
    Worker's Queue bindings, absent where the work runs at once; `jobs` (tests) holds all work until run."""
    clock = clock or SystemClock()
    audit = audit or Audit([print_sink], clock)
    ledger, contexts = build_contexts(settings, db, clock, audit, transport)
    return App(
        settings,
        db,
        clock,
        ledger,
        PaystackSimStore(db),
        contexts,
        build_connectors(
            settings,
            contexts,
            memory_context(settings, contexts, db, clock, audit),
            KnowledgeStore(db),
            WebReader(
                page_fetcher or WorkerPageFetch(),
                WebCache(db, clock),
                clock,
                Policy(settings.web_enabled, settings.web_deny),
            ),
            web_search_for(settings, db, clock, transport or WorkerFetch()),
            clock,
        ),
        build_background(
            settings,
            db,
            clock,
            audit,
            contexts,
            callback_transport or WorkerFetch(follow_redirects=False),
            queues,
            jobs,
        ),
    )
