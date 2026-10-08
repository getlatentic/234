# SPDX-License-Identifier: AGPL-3.0-or-later
"""The host's log lines (turns/logs.py, turns/trace.py): each is one JSON object carrying the chat, a hash of
its owner and the turn's task id; each tool call and each model round is a line of numbers and short words;
and no secret and no full account number reaches a line, in a message, a field or a traceback."""

import io
import json
import logging

import pytest

from turns import kinds, logs, trace
from turns.tool_calls import refusal_code

from .support import tool_call
from .test_metrics import SEND, Sink, core, settle

SECRET = "_".join(["sk", "live", "abcdefgh12345678"])
ACCOUNT = "0123456789"


@pytest.fixture
def lines():
    out = io.StringIO()
    handler = logging.StreamHandler(out)
    handler.addFilter(logs.ScrubFilter())
    handler.setFormatter(logs.JsonFormatter())
    root = logging.getLogger()
    root.addHandler(handler)
    before = root.level
    root.setLevel(logging.INFO)
    yield lambda: [json.loads(line) for line in out.getvalue().splitlines()]
    root.removeHandler(handler)
    root.setLevel(before)


def test_a_line_carries_the_chat_the_hashed_owner_and_the_task(lines):
    with trace.bound("chat-1", "owner-7", "task-9"):
        logging.getLogger("t").info("hello")
    (line,) = lines()
    assert (line["chat"], line["task"], line["msg"]) == ("chat-1", "task-9", "hello")
    assert line["owner"] == trace.owner_tag("owner-7") and "owner-7" not in json.dumps(line)


def test_a_line_outside_a_turn_has_no_context(lines):
    logging.getLogger("t").info("alone")
    (line,) = lines()
    assert not {"chat", "owner", "task"} & set(line)


def test_no_secret_and_no_full_account_number_reaches_a_line(lines):
    log = logging.getLogger("t")
    log.warning("sent to %s with key %s", ACCOUNT, SECRET)
    logs.event(log, "paid", account=ACCOUNT, note=f"token: {SECRET}", kobo=5000)
    try:
        raise RuntimeError(f"transfer to {ACCOUNT} refused by {SECRET}")
    except RuntimeError:
        log.exception("The transfer failed")
    text = json.dumps(lines())
    assert SECRET not in text and ACCOUNT not in text
    assert "0123***789" in text and '"kobo": 5000' in text
    assert lines()[2]["exc"].startswith("Traceback")


def test_a_link_keeps_its_origin_and_loses_its_credentials_and_query(lines):
    logging.getLogger("t").info("GET https://user:pw@api.example.com/pay/1?token=abc#frag")
    assert lines()[0]["msg"] == "GET https://api.example.com/pay/1"


def test_a_refusal_code_is_the_leading_capitals_of_a_tool_error():
    assert refusal_code("LIMIT_EXCEEDED: too much") == "LIMIT_EXCEEDED"
    assert refusal_code("no code here") is None


async def test_a_turn_logs_each_round_and_tool_call_with_one_task_id(lines, chat, sql, clock):
    made, _ = core(
        chat,
        sql,
        clock,
        Sink(),
        ("", [tool_call(SEND, {}, "c1")]),
        "Done.",
    )
    await made.submit(kinds.USER, "send it")
    await settle(made)
    mine = [line for line in lines() if line["msg"] in ("round", "tool")]
    assert [line["msg"] for line in mine] == ["round", "tool", "round"]
    assert len({line["task"] for line in mine}) == 1 and {line["chat"] for line in mine} == {chat.id}
    tool = mine[1]
    assert (tool["tool"], tool["outcome"], tool["is_error"]) == (
        "send",
        "ok",
        False,
    ) and "duration_ms" in tool
    assert mine[0]["tool_calls"] == 1 and mine[0]["finish_reason"]
