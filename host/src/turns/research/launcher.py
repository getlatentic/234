# SPDX-License-Identifier: AGPL-3.0-or-later
"""Starting a run's chat and posting its report, between Durable Objects: a run is a chat, so each is a
call to the chat Durable Object of that id."""

from typing import Any


class DoLauncher:
    """The Worker's `CHAT` binding: `launch` is called by the chat that starts a run, `report` by the run."""

    def __init__(self, env: Any) -> None:
        self._env = env

    async def launch(self, run: str, question: str) -> None:
        await self._env.CHAT.getByName(run).research(run, question)

    async def report(self, parent: str, run: str, text: str) -> None:
        await self._env.CHAT.getByName(parent).research_done(parent, run, text)
