# SPDX-License-Identifier: AGPL-3.0-or-later
"""The web tool through the running Worker: the Workers runtime's own fetch, its stream read and its manual
redirects, against a page that does not change (IANA's example.com). Needs the network. Run with
`pytest -m worker`."""

import httpx
import pytest

from tests.worker_client import ALICE, Mcp

pytestmark = pytest.mark.worker


@pytest.fixture
async def web():
    async with httpx.AsyncClient(timeout=60) as http:
        yield Mcp(http, "web", ALICE)


async def test_a_real_page_is_read_as_text_with_its_address(web):
    result = await web.call("web_fetch", url="https://example.com/")
    assert not result.get("isError"), result
    view = result["structuredContent"]["page"]
    assert view["url"] == "https://example.com/" and view["title"] == "Example Domain"
    assert "documentation examples" in view["text"] and view["truncated"] is False


async def test_a_private_address_is_refused_by_the_worker_too(web):
    for url in ("https://169.254.169.254/latest/meta-data", "http://example.com/", "https://localhost/"):
        refused = await web.call("web_fetch", url=url)
        assert refused["isError"] and refused["content"][0]["text"].startswith("BAD_ADDRESS")
