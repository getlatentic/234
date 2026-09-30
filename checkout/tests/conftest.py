# SPDX-License-Identifier: AGPL-3.0-or-later
import pytest

from tests.support import FakeClock, Stack, make_stack


@pytest.fixture
def stack() -> Stack:
    return make_stack()


@pytest.fixture
def clock(stack: Stack) -> FakeClock:
    return stack.clock


@pytest.fixture
def app(stack: Stack):
    return stack.app


@pytest.fixture
async def worker():
    """A client for the running Worker, on a clean ledger."""
    import httpx

    from tests.worker_client import BASE_URL, Mcp

    async with httpx.AsyncClient(timeout=30, limits=httpx.Limits(max_connections=100)) as http:
        await http.post(f"{BASE_URL}/test/reset")
        yield Mcp(http)
