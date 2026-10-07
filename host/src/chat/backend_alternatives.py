# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Django side's backend when the turn runner is not a Durable Object (`TURN_RUNNER=waituntil` or
`queue`): the chat's core is built in the Worker that took the request, and a turn is kept alive by
`ctx.waitUntil` or a Queue. The measured alternatives; see docs/durable-chat.md."""

from typing import Any

import httpx

from turns import kinds
from turns.alternatives import runners
from turns.hub import HubError

from .backend import WorkerBackend


class LocalBackend(WorkerBackend):
    def __init__(self, runner: str) -> None:
        super().__init__()
        self._runner = runner

    def _core(self, chat_id: str):
        env = self._env()
        starter = runners.start_with_wait_until if self._runner == "waituntil" else runners.queue_starter(env)
        return runners.local_core(env, chat_id, starter)

    def submit(
        self, chat_id: str, kind: str, text: str, task: str | None = None, scopes: list[str] | None = None
    ) -> dict[str, Any]:
        from pyodide.ffi import run_sync

        core = self._core(chat_id)
        if kind == kinds.CARD_CONTEXT:
            return run_sync(core.note(text))
        return run_sync(core.submit(kind, text, task, scopes))

    def cancel(self, chat_id: str) -> dict[str, Any]:
        """The measured alternatives keep no loop of their own to stop: only the Durable Object runner can."""
        return {"cancelled": False}

    def compact(self, chat_id: str, keep_recent_tokens: int | None = None) -> dict[str, Any]:
        from pyodide.ffi import run_sync

        return run_sync(self._core(chat_id).compact(keep_recent_tokens))

    def card_call(self, chat_id: str, server: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        from pyodide.ffi import run_sync

        try:
            return {"result": run_sync(self._core(chat_id).card_call(server, name, arguments))}
        except (HubError, httpx.HTTPError) as refused:
            return {
                "error": str(refused)
                if isinstance(refused, HubError)
                else "The connector could not be reached."
            }

    def refresh_card(self, chat_id: str, quote_id: str) -> bool:
        from pyodide.ffi import run_sync

        return run_sync(self._core(chat_id).refresh_card(quote_id))

    def quote_ended(self, chat_id: str, quote_id: str, event_id: str, text: str) -> bool:
        from pyodide.ffi import run_sync

        return run_sync(self._core(chat_id).quote_ended(quote_id, event_id, text))

    def erase(self, chat_id: str) -> None:
        from pyodide.ffi import run_sync

        run_sync(self._core(chat_id).purge())
