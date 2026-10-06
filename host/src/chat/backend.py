# SPDX-License-Identifier: AGPL-3.0-or-later
"""Everything a view needs from outside Django: the chat's Durable Object, the connectors and the rate
limiter. Views call these plain synchronous methods; in a Worker each bridges to the async runtime with
`run_sync`, and tests put a fake in its place."""

import json
from typing import Any, Protocol

from django.conf import settings

from config import runtime
from turns.binding import connector_client
from turns.hub import MEMORY_SERVER, CardPage, Hub, build_hub
from turns.ledger_owner import ledger_owner


class Backend(Protocol):
    def submit(self, chat_id: str, kind: str, text: str, task: str | None = None) -> dict[str, Any]: ...

    def cancel(self, chat_id: str) -> dict[str, Any]: ...

    def compact(self, chat_id: str, keep_recent_tokens: int | None = None) -> dict[str, Any]: ...

    def card_call(
        self, chat_id: str, server: str, name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]: ...

    def refresh_card(self, chat_id: str, quote_id: str) -> bool: ...

    def quote_ended(self, chat_id: str, quote_id: str, event_id: str, text: str) -> bool: ...

    def erase(self, chat_id: str) -> None: ...

    def card_page(self, server: str, uri: str) -> CardPage: ...

    def memory(self, owner: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]: ...

    def relay(
        self, server: str, body: bytes, headers: dict[str, str], owner: str, notes: bool
    ) -> tuple[int, dict[str, str], bytes]: ...

    def rate_ok(self, key: str) -> bool: ...


class WorkerBackend:
    def __init__(self) -> None:
        self._hub: Hub | None = None

    @staticmethod
    def _env() -> Any:
        from workers import env

        return env

    def _stub(self, chat_id: str) -> Any:
        return self._env().CHAT.getByName(chat_id)

    def submit(self, chat_id: str, kind: str, text: str, task: str | None = None) -> dict[str, Any]:
        from pyodide.ffi import run_sync

        return json.loads(run_sync(self._stub(chat_id).submit(chat_id, kind, text, task or "")))

    def cancel(self, chat_id: str) -> dict[str, Any]:
        from pyodide.ffi import run_sync

        return json.loads(run_sync(self._stub(chat_id).cancel(chat_id)))

    def compact(self, chat_id: str, keep_recent_tokens: int | None = None) -> dict[str, Any]:
        from pyodide.ffi import run_sync

        keep = -1 if keep_recent_tokens is None else keep_recent_tokens
        return json.loads(run_sync(self._stub(chat_id).compact(chat_id, keep)))

    def card_call(self, chat_id: str, server: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        from pyodide.ffi import run_sync

        answer = json.loads(
            run_sync(self._stub(chat_id).card_call(chat_id, server, name, json.dumps(arguments)))
        )
        return answer

    def refresh_card(self, chat_id: str, quote_id: str) -> bool:
        from pyodide.ffi import run_sync

        return json.loads(run_sync(self._stub(chat_id).refresh_card(chat_id, quote_id)))

    def quote_ended(self, chat_id: str, quote_id: str, event_id: str, text: str) -> bool:
        from pyodide.ffi import run_sync

        return json.loads(run_sync(self._stub(chat_id).quote_ended(chat_id, quote_id, event_id, text)))

    def erase(self, chat_id: str) -> None:
        from pyodide.ffi import run_sync

        run_sync(self._stub(chat_id).purge(chat_id))

    def _connectors(self) -> Hub:
        """Built on first use, so its token is read from the Worker's live secrets: the settings module is
        evaluated at startup and a rotated secret would not reach it."""
        if self._hub is None:
            import httpx

            self._hub = build_hub(
                settings.CHECKOUT_MCP_URL.rstrip("/"),
                tuple(settings.CONNECTORS),
                connector_client(
                    self._env(), runtime.get("CHECKOUT_MCP_BINDING", ""), httpx.AsyncClient(timeout=30)
                ),
                runtime.get("CHECKOUT_MCP_TOKEN", ""),
            )
        return self._hub

    def card_page(self, server: str, uri: str) -> CardPage:
        from pyodide.ffi import run_sync

        return run_sync(self._connectors().read_card(server, uri))

    def memory(self, owner: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """A call of the page's own to the memory connector, for the signed-in account whose chat owner string
        is `owner`."""
        from pyodide.ffi import run_sync

        return run_sync(self._connectors().call_app_tool(MEMORY_SERVER, name, arguments, ledger_owner(owner)))

    def relay(
        self, server: str, body: bytes, headers: dict[str, str], owner: str, notes: bool
    ) -> tuple[int, dict[str, str], bytes]:
        """An MCP message of an outside client, passed to a connector as `owner` (the OAuth gateway)."""
        from pyodide.ffi import run_sync

        answer = run_sync(self._connectors().relay(server, body, headers, owner, notes))
        return answer.status_code, dict(answer.headers), answer.content

    def rate_ok(self, key: str) -> bool:
        from js import Object
        from pyodide.ffi import run_sync, to_js

        limiter = getattr(self._env(), "CHAT_LIMITER", None)
        if limiter is None:
            return True
        outcome = run_sync(limiter.limit(to_js({"key": key}, dict_converter=Object.fromEntries)))
        return bool(outcome.success)


_backend: Backend | None = None


def get_backend() -> Backend:
    global _backend
    if _backend is None:
        runner = runtime.get("TURN_RUNNER", "do")
        if runner == "do":
            _backend = WorkerBackend()
        else:
            from .backend_alternatives import LocalBackend

            _backend = LocalBackend(runner)
    return _backend


def set_backend(backend: Backend | None) -> None:
    global _backend
    _backend = backend
