# SPDX-License-Identifier: AGPL-3.0-or-later
from pydantic import BaseModel

from checkout.mcp.registry import Tool


class Arguments(BaseModel):
    note: str | None = None


async def run(_):
    return {}


def test_a_tools_schema_is_built_once_however_often_the_tools_are_listed(monkeypatch):
    built = []
    original = Arguments.model_json_schema.__func__

    def counting(cls, *args, **kwargs):
        built.append(cls)
        return original(cls, *args, **kwargs)

    monkeypatch.setattr(Arguments, "model_json_schema", classmethod(counting))
    tool = Tool("t", "T", "A tool.", Arguments, run)
    first, second = tool.listed(), tool.listed()
    assert first == second
    assert first["inputSchema"] == {"type": "object", "properties": {"note": {"type": "string"}}}
    assert len(built) == 1
