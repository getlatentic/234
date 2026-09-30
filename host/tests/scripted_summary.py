# SPDX-License-Identifier: AGPL-3.0-or-later
"""A scripted summariser: what a model that kept to the instructions would write, and how it can fall short.

It reads the request the compaction sends (the earlier conversation between <conversation> tags, the previous
record between <previous_record> tags and, on a second try, the list of what the last record left out) and
writes the six sections from it. It depends on nothing of the host, so the scripted model server
(fake_model.py) and the unit tests use the same one.

Modes: faithful keeps every fact; forgetful drops every fact, even when asked again; forgets_first drops them
once and keeps what a second request lists; junk is not a summary.
"""

import re
from typing import Any

MARK = "You write the record of an earlier part of a conversation"
HEADINGS = (
    "## Asked and decided",
    "## Facts the person stated",
    "## Done",
    "## Pending",
    "## Open questions",
    "## Tone and language",
)
AMOUNT = re.compile(r"₦\s?\d[\d,]*(?:\.\d+)?|\b\d+(?:\.\d+)?k\b|\bN\d[\d,]*")
PHONE = re.compile(r"(?<!\d)(?:\+?234[\s-]?|0)[789][01]\d[\s-]?\d{3}[\s-]?\d{4}(?!\d)")
ACCOUNT = re.compile(r"(?<!\d)\d{10}(?!\d)")
PIDGIN = re.compile(r"\b(abeg|wetin|how far|no be|dey|sef|wahala|oga|na so|una|sabi|pikin|wey)\b", re.I)
QUOTE = re.compile(r"\[Quote (?:made|update)\]: (qt-[\w-]+) is (\w+)(.*)")
DONE = re.compile(r"- (qt-[\w-]+) is (\w+)\s*(.*)")
RECENT_REQUESTS = 5
LEFT_OUT = "left these out"


def is_summary_request(messages: list[dict[str, Any]]) -> bool:
    return bool(messages) and str(messages[0].get("content", "")).startswith(MARK)


def _between(text: str, tag: str) -> str:
    match = re.search(rf"<{tag}>\n(.*?)\n</{tag}>", text, re.S)
    return match.group(1) if match else ""


def _listed_facts(text: str) -> list[str]:
    tail = text.split(LEFT_OUT)[-1] if LEFT_OUT in text else ""
    return [line[2:] for line in tail.splitlines() if line.startswith("- ")]


def _quotes(lines: list[str]) -> dict[str, tuple[str, str]]:
    found: dict[str, tuple[str, str]] = {}
    for line in lines:
        if match := QUOTE.match(line):
            found[match[1]] = (match[2], match[3].strip(" ,."))
    return found


def _carried(previous: str, heading: str) -> list[str]:
    block = previous.split(heading)[-1].split("\n## ")[0] if heading in previous else ""
    return [line for line in block.splitlines() if line.startswith("- ")]


def _facts(person: list[str]) -> list[str]:
    text = "\n".join(person)
    found = {m.group().strip() for pattern in (AMOUNT, PHONE, ACCOUNT) for m in pattern.finditer(text)}
    return sorted(found)


def _section(heading: str, lines: list[str]) -> str:
    return heading + "\n" + ("\n".join(lines) if lines else "- nothing")


def _faithful(user: str) -> str:
    conversation, previous = _between(user, "conversation").splitlines(), _between(user, "previous_record")
    person = [line.removeprefix("[Person]: ") for line in conversation if line.startswith("[Person]: ")]
    quotes = {m[1]: (m[2], m[3]) for line in _carried(previous, "## Done") if (m := DONE.match(line))}
    quotes |= _quotes(conversation)
    asked = (_carried(previous, "## Asked and decided") + [f"- {p[:200]}" for p in person])[-RECENT_REQUESTS:]
    stated = sorted({*(f"- {f}" for f in _facts(person)), *_carried(previous, "## Facts the person stated")})
    done = [f"- {ref} is {state} {rest}".strip() for ref, (state, rest) in quotes.items()]
    pending = [
        f"- {ref} is still {state}" for ref, (state, _) in quotes.items() if state.startswith("awaiting")
    ]
    pidgin = bool(PIDGIN.search("\n".join(person))) or "Pidgin" in previous
    tone = ["- writes Pidgin, informal" if pidgin else "- writes English, plain"]
    return "\n\n".join(
        [
            _section(HEADINGS[0], asked),
            _section(HEADINGS[1], stated),
            _section(HEADINGS[2], done),
            _section(HEADINGS[3], pending),
            _section(HEADINGS[4], []),
            _section(HEADINGS[5], tone),
        ]
    )


def _forgetful(user: str) -> str:
    person = [
        line.removeprefix("[Person]: ")
        for line in _between(user, "conversation").splitlines()
        if line.startswith("[Person]: ")
    ]
    asked = [f"- asked about {len(person)} things" if person else "- nothing"]
    return "\n\n".join(
        [
            _section(HEADINGS[0], asked),
            _section(HEADINGS[1], ["- they gave some numbers"]),
            _section(HEADINGS[2], ["- a few payments were made"]),
            _section(HEADINGS[3], []),
            _section(HEADINGS[4], []),
            _section(HEADINGS[5], ["- writes English"]),
        ]
    )


def write(messages: list[dict[str, Any]], mode: str = "faithful", attempt: int = 0) -> str:
    user = messages[-1]["content"]
    if mode == "junk":
        return "ok"
    if mode == "forgetful" or (mode == "forgets_first" and attempt == 0):
        return _forgetful(user)
    text = _faithful(user)
    listed = _listed_facts(user)
    return text + ("\n" + "\n".join(f"- {line}" for line in listed) if listed else "")
