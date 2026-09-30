# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the live check prints: one line per check, with any key removed, and the counts."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from checkout.audit import redact_keys


@dataclass
class Report:
    ok: int = 0
    failed: int = 0
    notes: int = 0

    def say(self, text: str) -> None:
        print(redact_keys(text), flush=True)

    def passed(self, name: str, detail: str = "") -> None:
        self.ok += 1
        self.say(f"[ok]   {name}{': ' + detail if detail else ''}")

    def failure(self, name: str, detail: str) -> None:
        self.failed += 1
        self.say(f"[FAIL] {name}: {detail}")

    def note(self, name: str, detail: str) -> None:
        self.notes += 1
        self.say(f"[note] {name}: {detail}")

    async def check[T](
        self, name: str, work: Callable[[], Awaitable[T]], judge: Callable[[T], str | None]
    ) -> T | None:
        try:
            value = await work()
        except Exception as error:
            self.failure(name, str(error) or type(error).__name__)
            return None
        problem = judge(value)
        if problem is None:
            self.passed(name)
        else:
            self.failure(name, problem)
        return value
