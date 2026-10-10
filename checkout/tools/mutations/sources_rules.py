# SPDX-License-Identifier: AGPL-3.0-or-later
"""What a turn may do with sources (host turns/sources.py, messages.py, runner.py): a few searches, nothing
that changes something after reading one, earlier passages left out, and an answer's links and amounts
checked against what was read. Run against the host's own tests."""

from tools.mutations.model import Mutation
from tools.mutations.model import host_mutation as host

SOURCES = ["tests/test_sources.py"]

MUTATIONS: list[Mutation] = [
    host(
        "sources: a turn's searches are limited",
        "turns/sources.py",
        "return SEARCH_BUDGET if reading.calls >= budget else None",
        "return None",
        SOURCES,
    ),
    host(
        "sources: nothing that changes something runs after a source is read",
        "turns/sources.py",
        "if reading.read and not await read_only(qualified):",
        "if False:",
        SOURCES,
    ),
    host(
        "sources: only a source that answered counts as read",
        "turns/sources.py",
        'any(not e.payload["is_error"] for e in calls)',
        "bool(calls)",
        SOURCES,
    ),
    host(
        "sources: the person's next message lifts it",
        "turns/sources.py",
        "return events[last + 1 :]",
        "return events",
        SOURCES,
    ),
    host(
        "sources: the passages of an earlier question are left out",
        "turns/messages.py",
        'result.payload.get("server") in sources.SOURCE_SERVERS and result.seq < asked_at',
        "False",
        SOURCES,
    ),
    host(
        "sources: a link nobody gave is named",
        "turns/sources.py",
        "if _address(u) not in known_links]",
        "if False]",
        SOURCES,
    ),
    host(
        "sources: an amount nobody gave is named",
        "turns/sources.py",
        "if _digits(m.group(1) or m.group(2)) not in known_numbers",
        "if False",
        SOURCES,
    ),
    host(
        "sources: the person's own amount is not named",
        "turns/sources.py",
        'seen = read + " " + said',
        "seen = read",
        SOURCES,
    ),
    host(
        "sources: an answer is checked when the turn searched",
        "turns/runner.py",
        "if missing := sources.ungrounded(answer, read, said):",
        "if False:",
        SOURCES,
    ),
    host(
        "sources: a retrieval is logged",
        "turns/tool_calls.py",
        'logs.event(log, "retrieval", tool=outcome.tool, passages=len(passages), sources=found_in)',
        "pass",
        SOURCES,
    ),
    host(
        "sources: a page of the web is a source",
        "turns/sources.py",
        'SOURCE_SERVERS = frozenset({"knowledge", "web"})',
        'SOURCE_SERVERS = frozenset({"knowledge"})',
        SOURCES,
    ),
    host(
        "sources: a source's tool event is marked untrusted",
        "turns/tool_calls.py",
        '**({"untrusted": True} if sources.is_source(call["name"]) else {}),',
        "",
        SOURCES,
    ),
    host(
        "sources: the person is shown the source an answer draws on",
        "turns/runner.py",
        "for reference in sources.drawn_on(references, answer):",
        "for reference in []:",
        SOURCES,
    ),
    host(
        "sources: a source an answer shares little with is not shown",
        "turns/sources.py",
        "or len(shared) >= 3:",
        "or len(shared) >= 1:",
        SOURCES,
    ),
    host(
        "sources: a total of two figures that were read is theirs",
        "turns/sources.py",
        " | _totals(set(amounts_in(seen)))",
        "",
        SOURCES,
    ),
    host(
        "sources: a figure no two read figures make is not theirs",
        "turns/sources.py",
        "return {str(a + b) for a, b in combinations(values, 2)} | {str(b - a) for a, b in",
        "return {str(a + b) for a in values for b in values} | {str(b - a) for a, b in",
        SOURCES,
    ),
    host(
        "sources: a page that shares much less than the best is not shown",
        "turns/sources.py",
        "if score * 2 >= best][:MAX_SHOWN]",
        "if True][:MAX_SHOWN]",
        SOURCES,
    ),
    host(
        "sources: a shared figure weighs more than a word",
        "turns/sources.py",
        "FIGURE_WEIGHT = 3",
        "FIGURE_WEIGHT = 1",
        SOURCES,
    ),
]
