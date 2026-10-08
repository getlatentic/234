# SPDX-License-Identifier: AGPL-3.0-or-later
"""Test doubles for the seams: SQLite (with the schema Django's migrations made) behind the Db seam,
a manual clock, and the scripted model and connector that turns run against."""

import sqlite3
from typing import Any

from django.db import connection

from turns.db import Db, UniqueViolation


class SqliteDb(Db):
    """The test database's own SQLite connection, so raw SQL runs against the schema the ORM made."""

    def __init__(self) -> None:
        connection.ensure_connection()
        self._connection: sqlite3.Connection = connection.connection

    def _run(self, sql: str, params: tuple[Any, ...]) -> sqlite3.Cursor:
        try:
            cursor = self._connection.cursor()
            cursor.row_factory = sqlite3.Row
            return cursor.execute(sql, params)
        except sqlite3.IntegrityError as error:
            if "UNIQUE" in str(error) or "PRIMARY KEY" in str(error):
                raise UniqueViolation(str(error)) from error
            raise

    async def rows(self, sql: str, *params: Any) -> list[dict[str, Any]]:
        return [dict(row) for row in self._run(sql, params).fetchall()]

    async def row(self, sql: str, *params: Any) -> dict[str, Any] | None:
        found = await self.rows(sql, *params)
        return found[0] if found else None

    async def execute(self, sql: str, *params: Any) -> int:
        return self._run(sql, params).rowcount


class ManualClock:
    def __init__(self, at: int = 1_790_000_000_000) -> None:
        self.at = at

    def __call__(self) -> int:
        return self.at

    def advance(self, seconds: float) -> None:
        self.at += int(seconds * 1000)


class ScriptedModel:
    """Answers each round with the next script entry: a string (text) or (text, tool_calls); an
    exception in the script is raised mid-stream. It records the messages it was sent."""

    def __init__(self, *script) -> None:
        self.script = list(script)
        self.sent: list[list[dict]] = []
        self.offered: list[list[str]] = []

    async def stream(self, messages, tools):
        from turns.model import Finished, TextDelta

        self.sent.append(messages)
        self.offered.append([t["function"]["name"] for t in tools])
        step = self.script.pop(0)
        if isinstance(step, str):
            step = (step, [])
        text, calls = step
        for word in text.split(" ") if text else []:
            yield TextDelta(word + " ")
        if isinstance(calls, Exception):
            raise calls
        yield Finished("tool_calls" if calls else "stop", calls)


def tool_call(name: str, arguments: dict | str, call_id: str = "call_1") -> dict:
    import json

    raw = arguments if isinstance(arguments, str) else json.dumps(arguments)
    return {"id": call_id, "name": name, "arguments": raw}


def quote_result(
    phase: str = "awaiting_approval", quote_id: str = "qt-1", token: str | None = "tok-secret"
) -> dict:
    result: dict = {
        "content": [{"type": "text", "text": f"Quote {quote_id} is {phase}."}],
        "structuredContent": {"quote": {"id": quote_id, "phase": phase}},
    }
    if token:
        result["_meta"] = {"approvalToken": token}
    return result


class FakeHub:
    """The connectors, scripted: `results` maps a qualified tool name to a result or an exception."""

    def __init__(self, results: dict | None = None, card_uri: str | None = "ui://s/card.html") -> None:
        self.results = results or {}
        self.card_uri = card_uri
        self.calls: list[tuple[str, dict]] = []
        self.owners: list[str] = []
        self.keys: list[str] = []
        self.keyed_tools: set[str] = set()
        self.read_only_tools: set[str] = set()
        self.delays: dict[str, float] = {}
        self.subscriptions: list[tuple[str, dict, str]] = []
        self.refuse_subscriptions = False

    async def subscribe(self, server: str, params: dict, owner: str) -> None:
        from turns.hub import HubError

        if self.refuse_subscriptions:
            raise HubError("events/subscribe: the callback did not answer")
        self.subscriptions.append((server, params, owner))

    async def model_tools(self):
        return [{"type": "function", "function": {"name": name, "parameters": {}}} for name in self.results]

    async def keyed(self, qualified: str) -> bool:
        return qualified in self.keyed_tools

    async def read_only(self, qualified: str) -> bool:
        return qualified in self.read_only_tools

    async def repeatable(self, qualified: str) -> bool:
        return qualified in self.keyed_tools | self.read_only_tools

    async def status_tools(self, server: str) -> list[str]:
        return sorted(t for t in self.read_only_tools if t.startswith(f"{server}__"))

    async def call_model_tool(
        self, qualified: str, arguments: dict, owner: str, key: str, account: bool = False
    ):
        from turns.hub import ToolOutcome

        self.calls.append((qualified, arguments))
        self.owners.append(owner)
        self.keys.append(key)
        if qualified in self.delays:
            import asyncio

            await asyncio.sleep(self.delays[qualified])
        result = self.results[qualified]
        if isinstance(result, Exception):
            raise result
        server, _, tool = qualified.partition("__")
        return ToolOutcome(server, tool, result, self.card_uri if "structuredContent" in result else None)


class FakeSockets:
    """The sockets of a Durable Object: each has a cursor and collects the frames sent to it."""

    def __init__(self) -> None:
        self.frames: dict[str, list[dict]] = {}
        self.cursor: dict[str, int | None] = {}

    def open(self, name: str) -> str:
        self.frames[name], self.cursor[name] = [], None
        return name

    def sockets(self):
        return list(self.frames)

    def key(self, socket):
        return socket

    def sent(self, socket):
        return self.cursor[socket]

    def mark(self, socket, seq):
        self.cursor[socket] = seq

    def send(self, socket, text):
        import json

        self.frames[socket].append(json.loads(text))

    def seqs(self, socket) -> list[int]:
        return [f["seq"] for f in self.frames[socket] if "seq" in f]


class FakeAlarms:
    def __init__(self) -> None:
        self.at: int | None = None
        self.seen: int | None = None
        self.strikes = 0

    async def arm(self, at_ms: int) -> None:
        self.at = at_ms

    async def disarm(self) -> None:
        self.at = None

    async def unchanged(self, last_seq: int) -> int:
        self.strikes = self.strikes + 1 if self.seen == last_seq else 0
        self.seen = last_seq
        return self.strikes


class FakeBackend:
    """The Django side's window on the Worker runtime: it records what the views ask for."""

    def __init__(self) -> None:
        self.submitted: list[tuple] = []
        self.scopes: list[list[str] | None] = []
        self.allow = True
        self.rate_keys: list[str] = []
        self.limiters: list[str] = []
        self.answer: dict = {"seq": 1, "task": "t1"}
        self.card_answer: dict = {"result": {"content": [{"type": "text", "text": "ok"}]}}
        self.refreshed: list[tuple] = []
        self.ended: list[tuple] = []
        self.erased: list[str] = []
        self.cancelled: list[str] = []
        self.cancel_answer: dict = {"cancelled": True}
        self.compacted: list[tuple] = []
        self.compact_answer: dict = {"compacted": True, "seq": 9, "trigger": "manual"}
        self.html = "<html><body>card</body></html>"
        self.ui: dict = {}
        self.owner: str = ""
        self.memory_calls: list[tuple] = []
        self.memory_answers: dict[str, dict] = {}
        self.relayed: list[tuple] = []
        self.brands_ended: list[tuple] = []
        self.brand_revokes = False
        self.relay_answer: tuple = (
            200,
            {"content-type": "application/json", "mcp-session-id": "sess-2"},
            b"{}",
        )

    def submit(self, chat_id, kind, text, task=None, scopes=None):
        self.submitted.append((chat_id, kind, text, task))
        self.scopes.append(scopes)
        return self.answer

    def cancel(self, chat_id):
        self.cancelled.append(chat_id)
        return self.cancel_answer

    def compact(self, chat_id, keep_recent_tokens=None):
        self.compacted.append((chat_id, keep_recent_tokens))
        return self.compact_answer

    def card_call(self, chat_id, server, name, arguments):
        self.submitted.append((chat_id, "card_call", server, name, arguments))
        return self.card_answer

    def relay(self, server, body, headers, owner, notes):
        self.relayed.append((server, body, headers, owner, notes))
        return self.relay_answer

    def quote_ended(self, chat_id, quote_id, event_id, text):
        self.ended.append((chat_id, quote_id, event_id, text))
        return True

    def refresh_card(self, chat_id, quote_id):
        self.refreshed.append((chat_id, quote_id))
        return True

    def erase(self, chat_id):
        self.erased.append(chat_id)

    def card_page(self, server, uri):
        from turns.hub import CardPage

        return CardPage(self.html, self.ui)

    def memory(self, owner, name, arguments):
        self.memory_calls.append((owner, name, arguments))
        return self.memory_answers.get(
            name, {"content": [{"type": "text", "text": "ok"}], "structuredContent": {}}
        )

    def rate_ok(self, key, limiter="CHAT_LIMITER"):
        self.rate_keys.append(key)
        self.limiters.append(limiter)
        return self.allow

    def end_brand(self, owner, brand):
        self.brands_ended.append((owner, brand))
        return self.brand_revokes
