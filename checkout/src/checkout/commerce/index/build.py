# SPDX-License-Identifier: AGPL-3.0-or-later
"""Wiring for Paystack Index: the provider the directory lists, the accounts a card connects, and, where Index
is simulated, the simulator's store for its sign-in page and test routes. Simulated, 234 talks to the
simulator inside the Worker and nothing leaves it; live, it talks to Index's own addresses (settings.py) and
the redirect that brings a person back must be https on the chat host."""

from dataclasses import dataclass
from urllib.parse import urlsplit

from ...audit import Audit
from ...clock import Clock
from ...config import Settings
from ...db import Db
from ...errors import ConfigError
from ...ledger import Ledger
from ...transport import Transport
from .accounts import CALLBACK_PATH, IndexAccounts
from .attempts import Attempts
from .catalog import IndexCatalog
from .fulfil import IndexFulfilment
from .linking import Linking
from .oauth import METADATA_PATH, IndexOAuth
from .provider import IndexProvider
from .registrations import Registrations
from .secretbox import SecretBox
from .settings import ALLOWED_HOSTS
from .sim import IndexSimulator
from .sim_store import IndexSimStore
from .store import IndexStore
from .tokens import IndexTokens
from .wire import IndexSession

SIM_PATH = "/sim/index"


@dataclass(frozen=True)
class IndexParts:
    provider: IndexProvider
    accounts: IndexAccounts
    sim: IndexSimStore | None
    """The simulator's state, for its sign-in page and the test routes; none when Index is live."""
    base: str
    """Where the simulator's addresses begin (/sim/index on this Worker); empty when Index is live."""


def _redirect_for(settings: Settings, live: bool) -> str:
    chat = settings.host_public_url or settings.public_base_url
    if live and urlsplit(chat).scheme != "https":
        raise ConfigError(
            "INDEX_MODE=live needs HOST_PUBLIC_URL to be an https address: Index sends the person back to "
            "the chat host there."
        )
    return f"{chat.rstrip('/')}{CALLBACK_PATH}"


def build_index(
    settings: Settings, db: Db, clock: Clock, audit: Audit, ledger: Ledger, transport: Transport
) -> IndexParts:
    index, live = settings.index, settings.index.live
    sim = None if live else IndexSimStore(db, clock)
    base = "" if live else f"{settings.public_base_url.rstrip('/')}{SIM_PATH}"
    wire = transport if live else IndexSimulator(IndexSimStore(db, clock), clock, base)
    mcp_url = index.mcp_url if live else f"{base}/mcp"
    trusted = frozenset(f"https://{host}" for host in ALLOWED_HOSTS) if live else frozenset({_origin(base)})
    box = SecretBox(index.token_key or f"simulated-index-{settings.approval_secret}")
    store = IndexStore(db, clock, box)
    oauth = IndexOAuth(wire, f"{base or _origin(mcp_url)}{METADATA_PATH}", trusted, clock)

    def sessions(token: str) -> IndexSession:
        return IndexSession(wire, mcp_url, token)

    tokens = IndexTokens(store, oauth, clock)
    attempts = Attempts(db, clock, box)
    redirect = _redirect_for(settings, live)
    registrations = Registrations(store, oauth, mcp_url, redirect)
    catalog = IndexCatalog(db, clock, sessions, tokens, oauth, registrations.current)
    linking = Linking(attempts, tokens, sessions, store)
    accounts = IndexAccounts(store, attempts, oauth, catalog, linking, registrations, redirect, clock, audit)
    fulfilment = IndexFulfilment(ledger, tokens, sessions, clock, audit)
    provider = IndexProvider(catalog, store, tokens, sessions, fulfilment, index, ledger)
    audit.log("index.startup", mode=index.mode)
    return IndexParts(provider, accounts, sim, base)


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"
