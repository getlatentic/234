# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Django side reads the connectors' token and binding from the Worker's live values when it first
builds its hub: the settings module is evaluated at startup, and a rotated secret must still reach it."""

import json

from chat.backend import WorkerBackend
from tests.test_binding import FakeBinding, FakeReply

LIST = {"jsonrpc": "2.0", "id": 1, "result": {"tools": []}}


class Env:
    def __init__(self, binding: FakeBinding) -> None:
        self.SVC = binding


async def test_the_hub_uses_the_token_and_binding_read_when_it_is_built(settings, monkeypatch):
    settings.CONNECTORS = ["s"]
    settings.CHECKOUT_MCP_URL = "https://connectors.internal"
    live = {"CHECKOUT_MCP_BINDING": "SVC", "CHECKOUT_MCP_TOKEN": "rotated-token"}
    monkeypatch.setattr("chat.backend.runtime.get", lambda name, default=None: live.get(name, default))
    binding = FakeBinding(FakeReply(200, json.dumps(LIST).encode(), content_type="application/json"))
    monkeypatch.setattr(WorkerBackend, "_env", staticmethod(lambda: Env(binding)))
    hub = WorkerBackend()._connectors()
    await hub.tools("s")
    assert {call["headers"]["authorization"] for call in binding.sent} == {"Bearer rotated-token"}
    assert binding.sent[0]["url"] == "https://connectors.internal/s/mcp"
