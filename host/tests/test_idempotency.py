# SPDX-License-Identifier: AGPL-3.0-or-later
"""The idempotency key of a quote-making call is the host's: derived from the owner, the chat and the call's
own id, so a retry of a call repeats it and any other request has its own."""

import re

import pytest

from turns.calls import earlier_twin, used_ids, with_distinct_ids
from turns.eventlog import Event
from turns.idempotency import derive_key

OWNER = "c0ffee00" * 4
ACCEPTED = re.compile(r"[A-Za-z0-9._:-]{8,64}")  # the connectors' pattern (flows/inputs.py)
CHAT = "1" * 32


def test_the_same_owner_chat_and_call_always_give_the_same_key():
    assert derive_key(OWNER, CHAT, "call_1") == derive_key(OWNER, CHAT, "call_1")


@pytest.mark.parametrize(
    "other",
    [(OWNER, CHAT, "call_2"), (OWNER, "2" * 32, "call_1"), ("0badf00d" * 4, CHAT, "call_1")],
    ids=["another call", "another chat", "another owner"],
)
def test_a_call_in_another_chat_or_of_another_owner_has_another_key(other):
    assert derive_key(*other) != derive_key(OWNER, CHAT, "call_1")


def test_the_parts_cannot_be_moved_across_each_other_to_reach_the_same_key():
    assert derive_key("ab", "c", "d") != derive_key("a", "bc", "d") != derive_key("a", "b", "cd")


def test_a_key_is_an_opaque_digest_that_shows_none_of_its_parts():
    key = derive_key(OWNER, CHAT, "call_1")
    assert re.fullmatch(r"[0-9a-f]{40}", key)
    for part in (OWNER, CHAT, "call_1"):
        assert part not in key and part[:8] not in key


@pytest.mark.parametrize("call_id", ["", "call_0", "x" * 400, "functions.make:0", "ünï cödé ✓", "a b\n"])
def test_the_key_is_inside_what_the_connectors_accept_whatever_the_provider_calls_a_call(call_id):
    assert ACCEPTED.fullmatch(derive_key(OWNER, CHAT, call_id))


def call(call_id, name="s__make", arguments="{}"):
    return {"id": call_id, "name": name, "arguments": arguments}


class TestDistinctIds:
    def test_ids_a_provider_gave_are_kept_when_they_are_new(self):
        calls = [call("call_a"), call("call_b")]
        assert with_distinct_ids(calls, set(), "m1") == calls

    def test_an_id_the_chat_has_seen_or_one_twice_in_a_reply_or_none_is_made_new(self):
        calls = [call("call_0"), call("call_0"), call("")]
        ids = [c["id"] for c in with_distinct_ids(calls, {"call_0"}, "m1")]
        assert len(set(ids)) == 3 and all(ids) and "call_0" not in ids[:2]

    def test_the_ids_of_earlier_replies_are_read_from_the_log(self):
        reply = Event(3, "assistant", "t", None, {"tool_calls": [call("call_0"), call("call_1")]}, 0)
        silent = Event(4, "assistant", "t", None, {"text": "hi"}, 0)
        assert used_ids([reply, silent]) == {"call_0", "call_1"}


class TestTwins:
    def test_the_same_tool_with_the_same_arguments_is_a_twin_of_the_first(self):
        first, second = call("a", arguments='{"x": 1, "y": 2}'), call("b", arguments='{"y": 2, "x": 1}')
        assert earlier_twin([first, second], second) is first
        assert earlier_twin([first, second], first) is None

    def test_a_key_the_model_still_sends_is_not_part_of_what_is_asked(self):
        first = call("a", arguments='{"x": 1, "idempotency_key": "one"}')
        second = call("b", arguments='{"x": 1, "idempotency_key": "two"}')
        assert earlier_twin([first, second], second) is first

    @pytest.mark.parametrize(
        "other", [call("b", arguments='{"x": 2}'), call("b", name="s__other", arguments='{"x": 1}')]
    )
    def test_another_tool_or_other_arguments_is_no_twin(self, other):
        assert earlier_twin([call("a", arguments='{"x": 1}'), other], other) is None

    def test_arguments_that_are_not_json_have_no_twin(self):
        first, second = call("a", arguments="{oops"), call("b", arguments="{oops")
        assert earlier_twin([first, second], second) is None
