# SPDX-License-Identifier: AGPL-3.0-or-later
"""A live Paystack key stops a Worker from serving anything. Starts its own Worker on a second port with a
dummy live-shaped key (never a real one) and checks that every route refuses and the key is not echoed."""

import os
import signal
import subprocess
import time
from pathlib import Path

import httpx
import pytest

from tests.keys import fake_key

pytestmark = pytest.mark.worker

PORT = int(os.environ.get("STARTUP_TEST_PORT", "8881"))
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def worker_with_a_live_key():
    live = fake_key("live", "dummyDUMMY12345678")
    log = ROOT / ".wrangler" / "startup-test.log"
    log.parent.mkdir(exist_ok=True)
    with log.open("w") as out:
        process = subprocess.Popen(
            [
                "uv",
                "run",
                "pywrangler",
                "dev",
                "--port",
                str(PORT),
                "--var",
                f"PAYSTACK_TEST_SECRET_KEY:{live}",
            ],
            cwd=ROOT,
            stdout=out,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            for _ in range(120):
                time.sleep(1)
                if "Ready on" in log.read_text():
                    break
            else:
                pytest.fail("the Worker did not start")
            yield live
        finally:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=30)


def test_a_live_key_is_refused_at_startup_and_never_echoed(worker_with_a_live_key):
    live = worker_with_a_live_key
    for path in ("/health", "/paystack-pay/mcp", "/airtime/mcp", "/send-money/mcp", "/food-order/mcp"):
        response = httpx.post(
            f"http://localhost:{PORT}{path}", json={"jsonrpc": "2.0", "id": 1, "method": "ping"}, timeout=30
        )
        assert response.status_code == 500
        assert "live key" in response.text
        assert live not in response.text and "dummyDUMMY" not in response.text
    worker_lines = [
        line
        for line in (ROOT / ".wrangler" / "startup-test.log").read_text().splitlines()
        if "[wrangler:" in line
    ]
    assert worker_lines and not any("dummyDUMMY" in line for line in worker_lines)
