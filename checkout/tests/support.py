# SPDX-License-Identifier: AGPL-3.0-or-later
"""The whole stack in one process: the real ledger on in-memory SQLite (built from the migrations),
the real Paystack and VTpass clients over their simulators, and the real connectors. What a test
sees is what a host sees, minus the network."""

import json
from dataclasses import dataclass, field, replace
from typing import Any

from checkout.app import App, build_app
from checkout.audit import Audit
from checkout.config import Settings
from checkout.flows.airtime import AirtimeFlow
from checkout.flows.food import FoodFlow
from checkout.flows.payment import PaymentFlow
from checkout.flows.transfer import TransferFlow
from checkout.http import handle
from checkout.jobs import HeldJobs
from checkout.owner import OWNER_HEADER
from checkout.sqlite_db import SqliteDb

ALICE = "a1" * 16
BOB = "b0" * 16

# 2026-09-29 10:00:00 UTC, as the TypeScript tests' FakeClock.
START = 1_790_676_000_000


class FakeClock:
    def __init__(self, at: int = START) -> None:
        self.at = at

    def now(self) -> int:
        return self.at

    def advance(self, seconds: float) -> None:
        self.at += int(seconds * 1000)


@dataclass
class Stack:
    app: App
    clock: FakeClock
    db: SqliteDb
    audit_lines: list[str] = field(default_factory=list)
    jobs: HeldJobs = field(default_factory=HeldJobs)

    async def run_jobs(self) -> None:
        """The work queued after the requests so far: rechecks, then the deliveries they lead to."""
        await self.jobs.run_all()

    @property
    def ledger(self):
        return self.app.ledger

    def flow(self, name: str):
        ctx = self.app.contexts[name]
        return {
            "paystack-pay": PaymentFlow,
            "send-money": TransferFlow,
            "airtime": AirtimeFlow,
            "food-order": FoodFlow,
        }[name](ctx)

    @property
    def payments(self) -> PaymentFlow:
        return self.flow("paystack-pay")

    @property
    def transfers(self) -> TransferFlow:
        return self.flow("send-money")

    @property
    def airtime(self) -> AirtimeFlow:
        return self.flow("airtime")

    @property
    def food(self) -> FoodFlow:
        return self.flow("food-order")

    def override(self, connector: str, **changes: Any) -> None:
        """Swaps parts of one connector's context, for a test that makes a provider misbehave."""
        contexts = dict(self.app.contexts)
        contexts[connector] = replace(contexts[connector], **changes)
        object.__setattr__(self.app, "contexts", contexts)

    async def rows(self, sql: str, *params: Any) -> list[dict[str, Any]]:
        return await self.db.rows(sql, *params)

    async def count(self, table: str) -> int:
        return (await self.db.row(f"SELECT COUNT(*) AS n FROM {table}"))["n"]

    async def open_checkout(self, url: str) -> None:
        await handle(self.app, "GET", f"/sim/checkout/{url.rsplit('/', 1)[1]}", {}, b"")

    async def complete_checkout(self, url: str, outcome: str = "success") -> None:
        """Does what a person does on the simulated checkout page: opens it, then presses a button."""
        reference = url.rsplit("/", 1)[1]
        action = {"success": "pay", "failed": "decline", "abandoned": "close"}[outcome]
        await self.open_checkout(url)
        await handle(self.app, "POST", f"/sim/checkout/{reference}/{action}", {}, b"")

    async def mcp(
        self,
        connector: str,
        method: str,
        params: dict[str, Any] | None = None,
        owner: str | None = None,
        headers: dict[str, str] | None = None,
    ):
        """One JSON-RPC request through the HTTP surface, as the host sends it: `owner` goes in the owner
        header, and `headers` adds any other."""
        body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
        sent = {"content-type": "application/json", **(headers or {})}
        if owner is not None:
            sent[OWNER_HEADER] = owner
        response = await handle(self.app, "POST", f"/{connector}/mcp", sent, json.dumps(body).encode())
        return json.loads(response.body)

    async def call(self, connector: str, tool: str, **arguments: Any) -> dict[str, Any]:
        return (await self.mcp(connector, "tools/call", {"name": tool, "arguments": arguments}))["result"]

    async def call_as(self, owner: str, connector: str, tool: str, /, **arguments: Any) -> dict[str, Any]:
        answer = await self.mcp(connector, "tools/call", {"name": tool, "arguments": arguments}, owner)
        return answer["result"]


def make_stack(page_fetcher: Any = None, **settings: Any) -> Stack:
    clock = FakeClock()
    lines: list[str] = []
    base = {
        "approval_secret": "test-secret-not-real",
        "per_payment_limit_kobo": 5_000_000,
        "daily_limit_kobo": 10_000_000,
        "enable_test_routes": True,
        **settings,
    }
    db = SqliteDb()
    jobs = HeldJobs()
    app = build_app(
        Settings(**base), db, clock, Audit([lines.append], clock), jobs=jobs, page_fetcher=page_fetcher
    )
    return Stack(app, clock, db, lines, jobs)


def reload_app(stack: Stack, **settings: Any) -> None:
    """The same database and clock under different settings, as after a redeploy."""
    base = {"approval_secret": "test-secret-not-real", "enable_test_routes": True, **settings}
    rebuilt = build_app(
        Settings(**base),
        stack.db,
        stack.clock,
        Audit([stack.audit_lines.append], stack.clock),
        jobs=stack.jobs,
    )
    stack.app = rebuilt


@dataclass(frozen=True)
class Sent:
    method: str
    url: str
    headers: dict[str, str]
    body: Any


class ScriptedTransport:
    """A provider that answers from a function: return a `Reply`, or an exception to raise. Every call is "
    "kept."""

    def __init__(self, answer) -> None:
        self._answer = answer
        self.calls: list[Sent] = []

    async def send(self, method, url, *, headers, body, timeout_seconds):
        sent = Sent(
            method, url, {k.lower(): v for k, v in headers.items()}, json.loads(body) if body else None
        )
        self.calls.append(sent)
        result = self._answer(sent)
        if isinstance(result, Exception):
            raise result
        return result


def json_reply(body: Any, status: int = 200):
    from checkout.transport import Reply

    return Reply(status, json.dumps(body), "application/json")


class CountingVtpass:
    """The VTpass client with every call counted, to show how many times the provider was really asked."""

    def __init__(self, inner) -> None:
        self._inner = inner
        self.calls: dict[str, int] = {}

    def __getattr__(self, name):
        target = getattr(self._inner, name)

        async def counted(*args, **kwargs):
            self.calls[name] = self.calls.get(name, 0) + 1
            return await target(*args, **kwargs)

        return counted


class PaystackOverride:
    """The Paystack client with some calls replaced, to make one of them fail or answer oddly."""

    def __init__(self, inner, **replacements) -> None:
        self._inner = inner
        self._replacements = replacements
        self.calls: dict[str, int] = {}

    def __getattr__(self, name):
        self.calls.setdefault(name, 0)
        target = self._replacements.get(name) or getattr(self._inner, name)

        async def called(*args, **kwargs):
            self.calls[name] += 1
            return await target(*args, **kwargs)

        return called
