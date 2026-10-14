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
from .commerce.checks import AccountChecks
from .commerce.directory import DirectoryProvider
from .commerce.index.build import build_index
from .commerce.registry import Providers
from .commerce.vtpass_provider import bill_providers
from .config import CONNECTORS, Settings
from .connectors import airtime, food_order, merchants, pay, send_money
from .connectors import knowledge as knowledge_connector
from .connectors import memory as memory_connector
from .connectors import wallet as wallet_connector
from .connectors import web as web_connector
from .connectors.kit import CardReader
from .connectors.web import WebSearch
from .db import Db
from .errors import ConfigError
from .flows.context import Context
from .funding import Funding, build_funding
from .jobs import HeldJobs
from .knowledge.store import KnowledgeStore
from .ledger import Ledger, Limits
from .mcp.registry import Connector
from .memory.context import MemoryContext
from .memory.proposals import Proposals
from .memory.store import MemoryStore
from .metrics import Metrics
from .modes import Modes
from .owner import DEFAULT_OWNER
from .paystack.api import PaystackApi
from .paystack.client import PaystackClient
from .paystack.sim import PaystackSimulator
from .paystack.sim_store import PaystackSimStore
from .refunds.owed import RefundRequests
from .transport import Transport, WorkerFetch
from .vtpass.api import VtpassApi
from .vtpass.client import VtpassClient, VtpassCredentials
from .vtpass.sim import VtpassSimulator
from .vtpass.sim_store import VtpassSimStore
from .wallet.adjustments import Adjustments
from .wallet.journal import Journal
from .wallet.reconciliation import Reconciliation
from .wallet.spending import WalletSpending
from .wallet.topups import TopUps
from .wallet.treasury import Treasury
from .wallet.withdrawals import Withdrawals
from .web.cache import WebCache
from .web.fetcher import Fetcher, WorkerPageFetch
from .web.reader import Policy, WebReader
from .web.search import GatewaySearch
from .web.search_budget import SearchBudget

CARD_DIR = Path(__file__).parent / "card"
MENU_FILE = "menu.html"
MEMORY_CARD_FILE = "memory.html"
WALLET_CARD_FILE = "wallet.html"
CONNECT_CARD_FILE = "connect.html"
SIMULATED_KEY = "sk_test_simulated"
SIMULATED_VTPASS = VtpassCredentials("simulated", "simulated", "simulated")
FOOD_MERCHANT = "Simulated merchant: not Chowdeck"
SIMULATED_SHOPS = "Simulated merchants: not real shops"
MERCHANT_LABELS = {"food-order": FOOD_MERCHANT, "merchants": SIMULATED_SHOPS}
WALLET_CONNECTORS = ("airtime", "merchants")
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
    funding: Funding
    withdrawals: Withdrawals
    adjustments: Adjustments
    reconciliation: Reconciliation


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
        PaystackSimStore(db),
        checkout,
        transfer_otp=sim.transfer_otp,
        payouts_refused=sim.payouts_refused,
        settles_refunds=not settings.enable_test_routes,
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
    settings: Settings,
    db: Db,
    clock: Clock,
    audit: Audit,
    journal: Journal,
    transport: Transport | None = None,
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
    wallet = WalletSpending(journal, db, clock)
    refunds = RefundRequests(audit)
    index = build_index(settings, db, clock, audit, ledger, transport)
    bills_api, bills_mode = _vtpass_for(settings, db, clock, audit, transport)
    providers = Providers(
        DirectoryProvider(db, clock),
        index.provider,
        *bill_providers(db, bills_api, bills_mode, settings.bills_service_fee_kobo),
    )
    checks = AccountChecks(db, clock, ledger.owner)
    contexts: dict[str, Context] = {}
    for connector in CONNECTORS:
        paystack, paystack_mode = _paystack_for(settings, db, connector, transport)
        vtpass, vtpass_mode = (bills_api, bills_mode) if connector == "airtime" else (None, None)
        reason = (
            PAYOUTS_REASON
            if connector == "send-money" and paystack_mode == "simulated" and settings.paystack.secret_key
            else None
        )
        shown_vtpass = bills_mode if connector == "merchants" else vtpass_mode
        modes = Modes(paystack_mode, shown_vtpass, MERCHANT_LABELS.get(connector), reason)
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
            wallet=wallet if connector in WALLET_CONNECTORS else None,
            refunds=refunds,
            providers=providers if connector == "merchants" else None,
            index=index if connector == "merchants" else None,
            checks=checks if connector == "merchants" else None,
            free_text_merchants=settings.free_text_merchants,
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


def withdrawals_for(
    settings: Settings, contexts: Mapping[str, Context], journal: Journal, db: Db, clock: Clock, audit: Audit
) -> Withdrawals:
    """Withdrawals are paid as transfers are, through the send-money connector's Paystack."""
    paystack = contexts["send-money"].paystack
    return Withdrawals(db, clock, journal, paystack, settings.approval_secret, audit)


def build_connectors(
    settings: Settings,
    contexts: Mapping[str, Context],
    memory: MemoryContext,
    knowledge: KnowledgeStore,
    reader: WebReader,
    topups: TopUps,
    withdrawals: Withdrawals,
    db: Db,
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
        merchants.build_connector(contexts["merchants"], card, card_reader(CONNECT_CARD_FILE)),
        memory_connector.build_connector(memory, card_reader(MEMORY_CARD_FILE)),
        knowledge_connector.build_connector(knowledge, memory.audit),
        web_connector.build_connector(reader, memory.audit, search, clock),
        wallet_connector.build_connector(
            topups, withdrawals, db, memory.audit, card_reader(WALLET_CARD_FILE)
        ),
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
    metrics: Metrics | None = None,
) -> App:
    """`callback_transport` reaches event subscribers (the chat host through its binding); `queues` are the
    Worker's Queue bindings, absent where the work runs at once; `jobs` (tests) holds all work until run;
    `metrics` records each wallet movement (none: nothing is recorded)."""
    clock = clock or SystemClock()
    audit = audit or Audit([print_sink], clock)
    journal = Journal(db, clock, settings.wallet, metrics)
    ledger, contexts = build_contexts(settings, db, clock, audit, journal, transport)
    funding = build_funding(settings, db, clock, audit, journal, transport or WorkerFetch())
    withdrawals = withdrawals_for(settings, contexts, journal, db, clock, audit)
    treasury = Treasury(funding.bachs, contexts["send-money"].paystack, contexts["airtime"].vtpass, audit)
    reconciliation = Reconciliation(db, clock, treasury, audit)
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
            funding.topups,
            withdrawals,
            db,
            web_search_for(settings, db, clock, transport or WorkerFetch()),
            clock,
        ),
        build_background(
            settings,
            db,
            clock,
            audit,
            contexts,
            funding.topups,
            withdrawals.outcomes,
            callback_transport or WorkerFetch(follow_redirects=False),
            queues,
            jobs,
            reconciliation,
        ),
        funding,
        withdrawals,
        Adjustments(db, clock, journal, audit),
        reconciliation,
    )
