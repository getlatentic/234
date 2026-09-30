# SPDX-License-Identifier: AGPL-3.0-or-later
"""Answers to questions about the chat's own past, read from the messages the model is sent, the way a model
that reads its context carefully would, and from nothing else. A test that gets the right answer from this has
shown that the context holds it, in a place a reader can find.

Depends on nothing of the host, so the scripted model server (fake_model.py) and the unit tests use it alike.
"""

import re
from typing import Any

SUMMARY_MARK = "[Summary of the earlier conversation."
PAID = re.compile(
    r"\[card update\].*?\((₦[\d,]+)(?:\.\d+)?\).*now shows: (?:succeeded|Payment successful)", re.S
)
LAST_PAID = re.compile(r"last (?:amount|thing) I paid", re.I)
STILL_OPEN = re.compile(r"(?:which|what) quote is still open", re.I)


def _texts(sent: list[dict[str, Any]]) -> list[str]:
    return [m["content"] for m in sent if isinstance(m.get("content"), str)]


def last_paid(sent: list[dict[str, Any]]) -> str | None:
    """The amount of the newest payment a card reported in the messages, else of the newest quote the summary
    lists as succeeded."""
    texts = _texts(sent)
    for text in reversed(texts):
        if found := PAID.search(text):
            return found[1]
    summary = next((t for t in texts if t.startswith(SUMMARY_MARK)), "")
    done = [line for line in summary.splitlines() if re.match(r"- qt-\S+ is succeeded", line)]
    return re.search(r"₦[\d,]+", done[-1])[0] if done else None


def open_quote(sent: list[dict[str, Any]]) -> str | None:
    """The newest quote the messages show that nothing says is settled."""
    texts = _texts(sent)
    made = [m[1] for t in texts for m in re.finditer(r"Quote (qt-[0-9a-f]+)[: ]", t)]
    return made[-1] if made else None


def answer(sent: list[dict[str, Any]]) -> str | None:
    """A reply to the last message when it asks about the past, else None."""
    last = sent[-1]
    text = last["content"] if last["role"] == "user" and isinstance(last["content"], str) else ""
    if LAST_PAID.search(text):
        amount = last_paid(sent)
        return f"The last amount you paid was {amount}." if amount else "I do not see a payment of yours."
    if STILL_OPEN.search(text):
        quote = open_quote(sent)
        return f"Quote {quote} is still open." if quote else "No quote is open."
    return None
