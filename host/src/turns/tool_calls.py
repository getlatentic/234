# SPDX-License-Identifier: AGPL-3.0-or-later
"""One tool call of a model's reply, run and logged: refused when its arguments are not JSON or the turn may
not make it (permissions.py), answered from the earlier call when it repeats a quote request of the same
reply, otherwise sent to its connector as the chat's ledger owner with a key derived from the call. A result
that carries a card is logged as one, and the host follows its quote's events.

A call is marked `tool.started` before it leaves, and has a deadline. When a call that changes something has
no answer, because the connector was too slow or the turn was cut off after it left, its outcome is unknown:
it is not sent again, and the model is told to check before it repeats it. A call that only reads, or that the
ledger remembers by its key, is safe to send again."""

import asyncio
import logging
import re
from collections.abc import Callable
from typing import Any

import httpx

from . import calls as call_rules
from . import kinds, logs, permissions, quote_events
from .card_calls import card_ref
from .eventlog import Draft, EventLog
from .hub import Hub, HubError, ToolOutcome, refused
from .idempotency import derive_key
from .ledger_owner import is_account, ledger_owner
from .metrics import Metrics
from .settings import Settings

log = logging.getLogger(__name__)
REFUSAL = re.compile(r"^([A-Z][A-Z0-9_]{2,}):")
UNREACHABLE = "The connector could not be reached."
BAD_ARGUMENTS = "The tool arguments were not valid JSON."
TOO_SLOW = "{tool} did not answer in time."
UNKNOWN = "{why} Whether it went through is unknown, so do not repeat it before checking: {check}."
WHY_SLOW = "{tool} did not answer in time."
WHY_CUT_OFF = "234 was restarted while {tool} was running."
CHECK_WITH = "call {tools} to see how it stands"
CHECK_WITH_PERSON = "ask the person to check"


def refusal_code(text: str) -> str | None:
    """The code a connector refused with (`LIMIT_DAILY: …`), when the result starts with one."""
    found = REFUSAL.match(text)
    return found.group(1) if found else None


class ToolCalls:
    def __init__(
        self,
        log: EventLog,
        hub: Hub,
        settings: Settings,
        clock: Callable[[], int] | None = None,
        metrics: Metrics | None = None,
    ) -> None:
        self._log, self._hub, self._settings = log, hub, settings
        self._clock, self._metrics = clock or (lambda: 0), metrics or Metrics()

    async def run(
        self,
        call: dict[str, Any],
        reply_calls: list[dict[str, Any]],
        permits: permissions.Permissions,
        owner: str,
        task: str | None,
        started: bool = False,
    ) -> None:
        """`started`: the log already holds this call's `tool.started` (the turn was cut off after it)."""
        arguments = call_rules.arguments_of(call)
        refusal = permits.refusal(call["name"])
        marks: dict[str, Any] = {}
        began, measured = self._clock(), "refused"
        if arguments is None:
            outcome = refused("", call["name"], BAD_ARGUMENTS)
        elif refusal is not None:
            outcome, marks = refusal.outcome, permissions.marks(permits, call["name"], refusal)
        elif twin := await self._twin_in_reply(call, reply_calls):
            outcome, measured = await self._repeat_of(call["name"], twin), "repeat"
        elif started and not await self._hub.repeatable(call["name"]):
            outcome, measured = await self._unknown(call["name"], WHY_CUT_OFF), "unknown"
        else:
            if not started:
                await self._started(call["name"], call["id"], task)
            outcome, measured = await self._call(call, arguments, owner)
            marks = permissions.marks(permits, call["name"], None)
        took = self._clock() - began
        self._metrics.tool(outcome.server, outcome.tool, measured, took)
        code = refusal_code(outcome.text) if outcome.is_error else None
        logs.event(
            log, "tool", server=outcome.server, tool=outcome.tool, outcome=measured, duration_ms=took,
            is_error=outcome.is_error, code=code,
        )  # fmt: skip
        payload = {
            "call_id": call["id"],
            "server": outcome.server,
            "tool": outcome.tool,
            "arguments": arguments or {},
            "result_text": outcome.text,
            "is_error": outcome.is_error,
            "duration_ms": took,
            **({"code": code} if code else {}),
            **marks,
        }
        card = self._card(outcome, task)
        await self._log.append_all([Draft(kinds.TOOL, payload, task), *([card] if card else [])])
        if card:
            await quote_events.follow(self._hub, self._settings, outcome, ledger_owner(owner))

    def _card(self, outcome: ToolOutcome, task: str | None) -> Draft | None:
        """The card the result asks for, appended in the same write as the result: a result logged without
        its card would never be run again, and the person could not approve the quote it made."""
        ref = card_ref(outcome.result)
        if not (outcome.card_uri and not outcome.is_error and ref):
            return None
        payload = {
            "server": outcome.server,
            "tool": outcome.tool,
            "resource_uri": outcome.card_uri,
            "result": outcome.result,
        }
        return Draft(kinds.CARD, payload, task, ref)

    async def _twin_in_reply(
        self, call: dict[str, Any], reply_calls: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        """The earlier call of this reply that made the same quote request, when this one repeats it."""
        twin = call_rules.earlier_twin(reply_calls, call)
        return twin if twin and await self._hub.keyed(call["name"]) else None

    async def _repeat_of(self, name: str, twin: dict[str, Any]) -> ToolOutcome:
        events = await self._log.context()
        first = next(e for e in events if e.type == kinds.TOOL and e.payload["call_id"] == twin["id"])
        server, _, tool = name.partition("__")
        text = call_rules.REPEATED + first.payload["result_text"]
        result = {"isError": first.payload["is_error"], "content": [{"type": "text", "text": text}]}
        return ToolOutcome(server, tool, result, None)

    async def _started(self, name: str, call_id: str, task: str | None) -> None:
        server, _, tool = name.partition("__")
        await self._log.append(
            kinds.TOOL_STARTED, {"call_id": call_id, "server": server, "tool": tool}, task=task
        )

    async def _call(
        self, call: dict[str, Any], arguments: dict[str, Any], owner: str
    ) -> tuple[ToolOutcome, str]:
        """The connector's answer, and how it went: ok, error, slow, unknown or unreachable."""
        ledger = ledger_owner(owner)
        key = derive_key(ledger, self._log.chat_id, call["id"])
        name = call["name"]
        server, _, tool = name.partition("__")
        try:
            async with asyncio.timeout(self._settings.tool_deadline_seconds):
                outcome = await self._hub.call_model_tool(name, arguments, ledger, key, is_account(owner))
        except TimeoutError:
            if await self._hub.read_only(name):
                return refused(server, tool, TOO_SLOW.format(tool=tool)), "slow"
            return await self._unknown(name, WHY_SLOW), "unknown"
        except HubError, httpx.HTTPError:
            return refused(server, tool, UNREACHABLE), "unreachable"
        return outcome, "error" if outcome.is_error else "ok"

    async def _unknown(self, name: str, why: str) -> ToolOutcome:
        server, _, tool = name.partition("__")
        status = await self._hub.status_tools(server)
        check = CHECK_WITH.format(tools=" or ".join(status)) if status else CHECK_WITH_PERSON
        return refused(server, tool, UNKNOWN.format(why=why.format(tool=tool), check=check))
