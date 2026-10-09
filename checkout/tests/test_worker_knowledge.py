# SPDX-License-Identifier: AGPL-3.0-or-later
"""The knowledge connector through the running Worker and its local D1 (workerd, Pyodide), over the fixture
corpus tools/up.sh loads: full-text search with FTS5 and its triggers work where the Worker runs, not only
in SQLite. Run with `pytest -m worker`."""

import httpx
import pytest

from tests.worker_client import ALICE, Mcp

pytestmark = pytest.mark.worker


@pytest.fixture
async def knowledge():
    async with httpx.AsyncClient(timeout=30) as http:
        yield Mcp(http, "knowledge", ALICE)


async def test_a_question_finds_the_published_passage_with_its_source(knowledge):
    found = await knowledge.call("search_knowledge", query="how do I renew my licence")
    (passage,) = found["structuredContent"]["passages"]
    assert passage["source_id"] == "frsc-licence-renewal" and passage["retrieved_at"] == "2026-10-01"
    assert "evil.example.com" not in found["content"][0]["text"]


async def test_a_draft_is_not_served_and_a_yoruba_question_without_marks_finds_its_page(knowledge):
    draft = await knowledge.call("search_knowledge", query="enrolment unreviewed nobody")
    assert draft["structuredContent"]["passages"] == []
    yoruba = await knowledge.call("search_knowledge", query="iforukosile")
    assert [p["source_id"] for p in yoruba["structuredContent"]["passages"]] == ["jamb-yoruba"]


async def test_sources_are_listed_and_a_passage_opens_with_its_neighbours(knowledge):
    listed = await knowledge.call("list_sources")
    assert [s["agency"] for s in listed["structuredContent"]["sources"]] == ["FRSC", "JAMB"]
    opened = await knowledge.call("open_source", passage_id="frsc-licence-renewal#0")
    assert opened["structuredContent"]["passages"][0]["passage_id"] == "frsc-licence-renewal#0"
