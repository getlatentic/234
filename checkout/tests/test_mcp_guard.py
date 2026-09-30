# SPDX-License-Identifier: AGPL-3.0-or-later
"""A tool never lets card details through in either direction, turns a refusal into a readable error and
hides an unexpected failure. Ported from the TypeScript demo's guarded.test.ts."""

import json

from pydantic import BaseModel, ConfigDict

from checkout.audit import Audit
from checkout.errors import DomainError
from checkout.mcp.registry import Tool
from tests.keys import fake_key
from tests.support import FakeClock


class Anything(BaseModel):
    model_config = ConfigDict(extra="allow")


def setup():
    lines: list[str] = []
    return Audit([lines.append], FakeClock()), lines


def tool_running(run) -> Tool:
    return Tool("t", "t", "a test tool", Anything, run)


def text_of(result) -> str:
    return result["content"][0]["text"]


async def test_passes_a_good_result_through():
    audit, _ = setup()

    async def run(_):
        return {"content": [{"type": "text", "text": "fine"}]}

    assert await tool_running(run).call({"a": 1}, audit) == {"content": [{"type": "text", "text": "fine"}]}


async def test_turns_a_refusal_into_a_readable_error_with_its_code():
    audit, _ = setup()

    async def run(_):
        raise DomainError("LIMIT_DAILY", "Too much today.")

    result = await tool_running(run).call({}, audit)
    assert result["isError"] is True and text_of(result) == "LIMIT_DAILY: Too much today."


async def test_refuses_a_card_number_in_the_input_before_running_anything():
    audit, lines = setup()
    ran = []

    async def run(_):
        ran.append(1)
        return {"content": []}

    result = await tool_running(run).call({"note": "4084 0840 8408 4081"}, audit)
    assert ran == []
    assert text_of(result).startswith("CARD_DATA_REFUSED")
    assert "guard.card_data_refused" in "\n".join(lines)
    assert "4084" not in "\n".join(lines)


async def test_withholds_a_result_that_holds_a_card_number():
    audit, lines = setup()

    async def run(_):
        return {"content": [{"type": "text", "text": "card 4084084084084081"}]}

    result = await tool_running(run).call({}, audit)
    assert result["isError"] is True
    assert text_of(result).startswith("CARD_DATA_REFUSED") and "4084" not in text_of(result)
    assert "guard.card_data_refused" in "\n".join(lines)


async def test_checks_structured_content_too():
    audit, _ = setup()

    async def run(_):
        return {
            "content": [{"type": "text", "text": "ok"}],
            "structuredContent": {"deep": {"card": "5060 6666 6666 6666 666"}},
        }

    assert (await tool_running(run).call({}, audit))["isError"] is True


async def test_does_not_scan_meta_where_the_approval_token_lives():
    audit, _ = setup()

    async def run(_):
        return {
            "content": [{"type": "text", "text": "ok"}],
            "_meta": {"approvalToken": "4084 0840 8408 4081"},
        }

    assert "isError" not in await tool_running(run).call({}, audit)


async def test_hides_an_unexpected_error_from_the_caller_and_records_it_without_secrets():
    audit, lines = setup()

    async def run(_):
        raise RuntimeError(f"boom with {fake_key('test', 'secretsecret123')}")

    result = await tool_running(run).call({}, audit)
    assert result["isError"] is True
    assert text_of(result).startswith("INTERNAL: ") and "boom" not in text_of(result)
    logged = "\n".join(lines)
    assert "tool.error" in logged and "secretsecret123" not in logged


async def test_reads_arguments_it_cannot_as_a_readable_error_naming_the_field():
    audit, _ = setup()

    class Strict(BaseModel):
        model_config = ConfigDict(extra="forbid")
        amount: int

    async def run(_):
        return {"content": []}

    result = await Tool("t", "t", "d", Strict, run).call({"amount": "x", "extra": 1}, audit)
    assert result["isError"] and "amount" in text_of(result) and "extra" in text_of(result)
    assert json.loads(json.dumps(result))
