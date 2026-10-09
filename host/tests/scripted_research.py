# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the scripted model does with 234's research (turns/research/), the way a model that follows the
prompt would. In a chat: "research <question>" starts a run, and it says so; when the run's report arrives as
an event it reports the findings. In the run's own chat (its prompt names the job): it searches the sources
for the question and writes down the amount the passage gives. Used by fake_model.py."""

import re
from typing import Any

START = "research__start_research"
SEARCH = "knowledge__search_knowledge"
RUN = "researching one question for a person who is not waiting"
ASK = re.compile(r"^research (?P<question>.+)$", re.I)
AMOUNT = re.compile(r"\d[\d,]* naira")
REPORT = "[event] The research you started has finished"


def _content(message: dict[str, Any]) -> str:
    return message["content"] if isinstance(message.get("content"), str) else ""


def _is_run(messages: list[dict[str, Any]]) -> bool:
    return messages[0]["role"] == "system" and RUN in _content(messages[0])


def _in_run(messages: list[dict[str, Any]]) -> dict[str, Any]:
    last = messages[-1]
    if last["role"] == "tool":
        found = AMOUNT.search(_content(last))
        return {"text": f"The licence renewal fee is {found[0]}." if found else "Nothing was found."}
    return {"tool": SEARCH, "arguments": {"query": _content(last)}}


def answer(messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any] | None:
    if _is_run(messages):
        return _in_run(messages)
    last = messages[-1]
    content = _content(last)
    if last["role"] == "tool" and content.startswith("Started."):
        return {"text": "I am researching it; the report will arrive in this chat."}
    if last["role"] == "user" and content.startswith(REPORT):
        return {"text": "The research found: " + (AMOUNT.search(content) or ["nothing"])[0] + "."}
    found = ASK.match(content) if last["role"] == "user" else None
    if found and any(t["function"]["name"] == START for t in tools):
        return {"tool": START, "arguments": {"question": found["question"]}}
    return None
