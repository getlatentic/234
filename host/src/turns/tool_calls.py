# SPDX-License-Identifier: AGPL-3.0-or-later
"""One tool call of a model's reply, run and logged: refused when its arguments are not JSON or the turn may
not make it (permissions.py), answered from the earlier call when it repeats a quote request of the same
reply, otherwise sent to its connector as the chat's ledger owner with a key derived from the call. A result
that carries a card is logged as one, and the host follows its quote's events."""

from typing import Any

import httpx

from . import calls as call_rules
from . import kinds, permissions, quote_events
from .card_calls import card_ref
from .eventlog import EventLog
from .hub import Hub, HubError, ToolOutcome, refused
from .idempotency import derive_key
from .ledger_owner import ledger_owner
from .settings import Settings

UNREACHABLE = "The connector could not be reached."
BAD_ARGUMENTS = "The tool arguments were not valid JSON."


class ToolCalls:
    def __init__(self, log: EventLog, hub: Hub, settings: Settings) -> None:
        self._log, self._hub, self._settings = log, hub, settings

    async def run(
        self,
        call: dict[str, Any],
        reply_calls: list[dict[str, Any]],
        permits: permissions.Permissions,
        owner: str,
        task: str | None,
    ) -> None:
        arguments = call_rules.arguments_of(call)
        refusal = permits.refusal(call["name"])
        marks: dict[str, Any] = {}
        if arguments is None:
            outcome = refused("", call["name"], BAD_ARGUMENTS)
        elif refusal is not None:
            outcome, marks = refusal.outcome, permissions.marks(permits, call["name"], refusal)
        elif twin := await self._twin_in_reply(call, reply_calls):
            outcome = await self._repeat_of(call["name"], twin)
        else:
            outcome = await self._call(call, arguments, owner)
            marks = permissions.marks(permits, call["name"], None)
        payload = {
            "call_id": call["id"],
            "server": outcome.server,
            "tool": outcome.tool,
            "arguments": arguments or {},
            "result_text": outcome.text,
            "is_error": outcome.is_error,
            **marks,
        }
        await self._log.append(kinds.TOOL, payload, task=task)
        await self._card(outcome, owner, task)

    async def _card(self, outcome: ToolOutcome, owner: str, task: str | None) -> None:
        ref = card_ref(outcome.result)
        if not (outcome.card_uri and not outcome.is_error and ref):
            return
        payload = {
            "server": outcome.server,
            "tool": outcome.tool,
            "resource_uri": outcome.card_uri,
            "result": outcome.result,
        }
        await self._log.append(kinds.CARD, payload, task=task, ref=ref)
        await quote_events.follow(self._hub, self._settings, outcome, ledger_owner(owner))

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

    async def _call(self, call: dict[str, Any], arguments: dict[str, Any], owner: str) -> ToolOutcome:
        ledger = ledger_owner(owner)
        key = derive_key(ledger, self._log.chat_id, call["id"])
        try:
            return await self._hub.call_model_tool(call["name"], arguments, ledger, key)
        except HubError, httpx.HTTPError:
            server, _, tool = call["name"].partition("__")
            return refused(server, tool, UNREACHABLE)
