# SPDX-License-Identifier: AGPL-3.0-or-later
"""A turn that cannot get anywhere ends, and no tool call runs twice by accident (host turns/): every
connector call has a deadline and is marked started before it leaves; after a restart only a call that is safe
to repeat runs again; resumes count only while nothing moves; and a watchdog that keeps finding nothing
changed stops. Run against the host's own tests."""

from tools.mutations.model import Mutation
from tools.mutations.model import host_mutation as host

RESILIENCE = ["tests/test_turn_resilience.py", "tests/test_chat_core.py", "tests/test_runner.py"]

MUTATIONS: list[Mutation] = [
    host(
        "turns: a connector call has a deadline",
        "turns/tool_calls.py",
        "            async with asyncio.timeout(self._settings.tool_deadline_seconds):",
        "            async with asyncio.timeout(None):",
        RESILIENCE,
    ),
    host(
        "turns: a slow call that changes something has an unknown outcome",
        "turns/tool_calls.py",
        "            if await self._hub.read_only(name):",
        "True:",
        RESILIENCE,
    ),
    host(
        "turns: a call is marked started before it leaves",
        "turns/tool_calls.py",
        "            if not started:\n                await self._started(",
        "            if False:\n                await self._started(",
        RESILIENCE,
    ),
    host(
        "turns: a call cut off after it left is not sent again unless that is safe",
        "turns/tool_calls.py",
        '        elif started and not await self._hub.repeatable(call["name"]):',
        "        elif False:",
        RESILIENCE,
    ),
    host(
        "turns: resumes without progress end the turn",
        "turns/runner.py",
        "        if counted >= self._settings.max_idle_resumes:",
        "        if False:",
        RESILIENCE,
    ),
    host(
        "turns: resumes close together count once",
        "turns/runner.py",
        "resumed.at - last_at >= self._settings.resume_window_seconds * 1000:",
        "True:",
        RESILIENCE,
    ),
    host(
        "turns: a turn with no progress for too long ends",
        "turns/runner.py",
        "        if self._clock() - progress.at > self._settings.no_progress_seconds * 1000:",
        "        if False:",
        RESILIENCE,
    ),
    host(
        "turns: a failed turn marks its input seen, so the next alarm does not restart it",
        "turns/runner.py",
        "kinds.FAILED, cause=cause, upto=upto)",
        "kinds.FAILED, cause=cause)",
        RESILIENCE,
    ),
    host(
        "turns: a turn given up answers the calls it left, so nothing trips over them later",
        "turns/runner.py",
        "            await self._stop_calls(INTERRUPTED)\n",
        "",
        RESILIENCE,
    ),
    host(
        "turns: a watchdog that keeps finding nothing changed stops",
        "turns/chat_core.py",
        "await self._alarms.unchanged(await self.log.last_seq()) >= self._settings.max_alarm_strikes:",
        "False:",
        RESILIENCE,
    ),
    host(
        "turns: a connector that sends no JSON-RPC reply is one that could not be reached",
        "turns/hub.py",
        '    if not isinstance(body, dict) or not ("result" in body or "error" in body):',
        "    if body is None:",
        ["tests/test_hub.py"],
    ),
]
