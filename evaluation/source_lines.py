# SPDX-License-Identifier: AGPL-3.0-or-later
"""Whether the source lines the host shows under an answer are proven by the pages the turn read (#645). Pure,
and independent of the host's own rule: it reads the lines from the notices and the pages from the text the
tool calls brought back, and compares the figures of the reply with the figures of each page."""

import re
from typing import Any

_LINE = re.compile(r"^Source: (?P<title>.+?)(?: — (?P<url>\S+))? \(read [^)]*\)$")
_BLOCK = re.compile(
    r"^\[\d+\] (?P<title>.+?) \((?P<meta>[^\n]*?)\); id \S+\n(?P<body>(?:>[^\n]*(?:\n|$))*)", re.M
)
_ADDRESS = re.compile(r"https?://[^\s,)]+")
_NUMBER = re.compile(r"\d{1,3}(?:[,\u202f\u00a0 ]\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")
_GROUPING = re.compile(r"[,\u202f\u00a0 ]")
_LIST_MARKER = re.compile(r"(?m)^[>\s]*(?:[-*]\s*)?\d+[.)]\s")


def figures(text: str) -> set[str]:
    """The numbers of a text as digits, without its links and the numbers that count a list."""
    bare = _LIST_MARKER.sub(" ", _ADDRESS.sub(" ", text))
    return {_GROUPING.sub("", n) for n in _NUMBER.findall(bare)}


def distinctive(figure: str) -> bool:
    """An amount, a percentage or a count that names one page's claim: not a day, a small count or a year."""
    return "." in figure or (int(figure) >= 100 and not 1900 <= int(figure) <= 2099)


def shown(turn: dict[str, Any]) -> list[tuple[str, str | None]]:
    """The title and the link of each source line the host added."""
    lines = (_LINE.match(n) for n in turn["notices"])
    return [(m["title"], m["url"]) for m in lines if m]


def pages(read: str) -> dict[str, str]:
    """The text the turn read of each page, by its link and by its title."""
    found: dict[str, str] = {}
    for block in _BLOCK.finditer(read):
        text = " ".join(line.removeprefix(">").strip() for line in block["body"].splitlines())
        for key in (block["title"], *_ADDRESS.findall(block["meta"])):
            found[key] = f"{found.get(key, '')} {text}"
    return found


def unproven(turn: dict[str, Any], read: str, words_ok: bool) -> list[str]:
    """Why a source line is not proven: its page holds none of the reply's figures that the turn read, or the
    lines together leave one of the distinctive ones out, or the reply has no such figure and `words_ok` does
    not allow a line on words alone."""
    lines = shown(turn)
    held = pages(read)
    claims = (figures(turn["reply"]) & figures(" ".join(held.values()))) - figures(turn["say"])
    if not claims:
        return (
            []
            if words_ok
            else [f"a line for {title!r} is shown under a reply with no figure read" for title, _ in lines]
        )
    problems, backed = [], set()
    for title, url in lines:
        mine = claims & figures(held.get(url or title, ""))
        backed |= mine
        if not mine:
            problems.append(f"the page {title!r} holds none of the figures {sorted(claims)}")
    if lines and (left := sorted(c for c in claims - backed if distinctive(c))):
        problems.append(f"the lines shown leave out the figures {left}")
    return problems
