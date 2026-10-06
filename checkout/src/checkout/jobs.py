# SPDX-License-Identifier: AGPL-3.0-or-later
"""Work the connectors do after answering: rechecking a quote a provider wrote about, and sending an event.
In the deployment each kind is a Cloudflare Queue (retries, a dead-letter queue); where no queue is bound
(local development without one, unit tests) the work runs at once, in the same order."""

from collections.abc import Awaitable, Callable
from typing import Any, Protocol

Job = dict[str, Any]


class Jobs(Protocol):
    async def send(self, job: Job) -> None: ...


class QueueJobs:
    def __init__(self, binding: Any) -> None:
        self._binding = binding

    async def send(self, job: Job) -> None:
        from js import Object
        from pyodide.ffi import to_js

        await self._binding.send(to_js(job, dict_converter=Object.fromEntries))


class InlineJobs:
    def __init__(self, run: Callable[[Job], Awaitable[None]]) -> None:
        self._run = run

    async def send(self, job: Job) -> None:
        await self._run(job)


class HeldJobs:
    """Jobs kept until they are run, as a Queue keeps them: the test stack's, so a test says when the work
    after a request happens."""

    def __init__(self) -> None:
        self.held: list[Job] = []
        self.run: Callable[[Job], Awaitable[None]] | None = None

    async def send(self, job: Job) -> None:
        self.held.append(job)

    async def run_all(self) -> None:
        while self.held and self.run is not None:
            await self.run(self.held.pop(0))
