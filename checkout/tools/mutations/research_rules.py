# SPDX-License-Identifier: AGPL-3.0-or-later
"""What keeps research on its own safe (host turns/research/, chat_core.py, sources.py): one run at a time
and a few a day, a run that reads only, its report posted once and taken as data, and a deadline. Run against
the host's own tests."""

from tools.mutations.model import Mutation
from tools.mutations.model import host_mutation as host

RESEARCH = ["tests/test_research.py"]

MUTATIONS: list[Mutation] = [
    host(
        "research: a chat has one run at a time",
        "turns/research/server.py",
        "if await self._store.running_for(parent):",
        "if False:",
        RESEARCH,
    ),
    host(
        "research: a person starts a few runs a day",
        "turns/research/server.py",
        'if await self._store.started_today(row["owner"]) >= self._settings.researches_per_day:',
        "if False:",
        RESEARCH,
    ),
    host(
        "research: a run starts only from a chat and with a question",
        "turns/research/server.py",
        "if row is None or len(question) < 5:",
        "if False:",
        RESEARCH,
    ),
    host(
        "research: a run past its deadline no longer blocks the chat",
        "turns/research/store.py",
        '"AND deadline_at > ? LIMIT 1"',
        '"AND ? > 0 LIMIT 1"',
        RESEARCH,
    ),
    host(
        "research: a run may use only the sources and the web",
        "turns/research/core.py",
        "servers=scope.servers_of(CONNECTORS),",
        "servers=(),",
        RESEARCH,
    ),
    host(
        "research: a run is told its job",
        "turns/research/core.py",
        "metrics=self._metrics, system=SYSTEM,",
        "metrics=self._metrics, system=None,",
        RESEARCH,
    ),
    host(
        "research: a run past its time stops and reports",
        "turns/research/core.py",
        'self._clock() >= run["deadline_at"]',
        "False",
        RESEARCH,
    ),
    host(
        "research: a run reports once",
        "turns/research/core.py",
        'if run is None or run["status"] != RUNNING:',
        "if run is None:",
        RESEARCH,
    ),
    host(
        "research: a chat takes a report once",
        "turns/chat_core.py",
        "if known is not None or self._erased:",
        "if self._erased:",
        RESEARCH,
    ),
    host(
        "research: a card number in a report is removed",
        "turns/chat_core.py",
        'report = redact_card_numbers(text, "[card number removed]")[:REPORT_CHARS]',
        "report = text[:REPORT_CHARS]",
        RESEARCH,
    ),
    host(
        "research: nothing that changes something runs on the strength of a report",
        "turns/sources.py",
        'reported or any(not e.payload["is_error"] for e in calls)',
        'any(not e.payload["is_error"] for e in calls)',
        RESEARCH,
    ),
    host(
        "research: a person's agent needs no scope to start research",
        "turns/permissions.py",
        "if self.scopes is None or sources.reads_only(qualified):",
        "if self.scopes is None:",
        RESEARCH,
    ),
    host(
        "research: the chat of a run is in no list",
        "chat/access.py",
        'Q(id__in=let_in), parent="")',
        "Q(id__in=let_in))",
        RESEARCH,
    ),
]
