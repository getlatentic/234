# SPDX-License-Identifier: AGPL-3.0-or-later
"""What 234 records about how it runs, in Workers Analytics Engine (the METRICS binding, docs/metrics.md): one
data point for each finished turn, each tool call and each health check. A data point holds kinds, names,
outcomes and numbers, never who asked or what was said: no owner, chat id, text or argument. Recording never
fails what it records; a Worker without the binding records nothing."""

import logging
from collections.abc import Sequence
from typing import Any, Protocol

log = logging.getLogger(__name__)

TURN, TOOL, HEALTH = "turn", "tool", "health"


class Sink(Protocol):
    def write(self, kind: str, blobs: Sequence[str], doubles: Sequence[float]) -> None: ...


class Nowhere:
    def write(self, kind: str, blobs: Sequence[str], doubles: Sequence[float]) -> None:
        return None


class AnalyticsEngine:
    def __init__(self, binding: Any) -> None:
        self._binding = binding

    def write(self, kind: str, blobs: Sequence[str], doubles: Sequence[float]) -> None:
        from js import Object
        from pyodide.ffi import to_js

        point = {"indexes": [kind], "blobs": [kind, *blobs], "doubles": list(doubles)}
        self._binding.writeDataPoint(to_js(point, dict_converter=Object.fromEntries))


class Metrics:
    """The data points, each with a fixed shape: blob1 is the kind, the rest as each method names them."""

    def __init__(self, sink: Sink | None = None) -> None:
        self._sink = sink or Nowhere()

    def _write(self, kind: str, blobs: Sequence[str], doubles: Sequence[float]) -> None:
        try:
            self._sink.write(kind, blobs, doubles)
        except Exception:
            log.warning("A %s data point could not be written", kind, exc_info=True)

    def turn(
        self,
        reason: str,
        cause: str,
        rounds: int,
        duration_ms: int,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> None:
        """blob2 reason (completed, input_required, failed, max_rounds, cancelled), blob3 cause ('' or why it
        failed); double1 duration, double2 model rounds, double3 prompt tokens, double4 completion tokens."""
        self._write(TURN, (reason, cause), (duration_ms, rounds, prompt_tokens, completion_tokens))

    def tool(self, server: str, tool: str, outcome: str, duration_ms: int) -> None:
        """blob2 connector, blob3 tool, blob4 outcome (ok, error, slow, unknown, unreachable, refused,
        repeat); double1 duration."""
        self._write(TOOL, (server, tool, outcome), (duration_ms,))

    def health(self, part: str, ok: bool, duration_ms: int) -> None:
        """blob2 what was checked (database, chats, a connector's name), blob3 ok or failed; double1
        duration."""
        self._write(HEALTH, (part, "ok" if ok else "failed"), (duration_ms,))


def metrics_of(env: Any) -> Metrics:
    binding = getattr(env, "METRICS", None)
    return Metrics(AnalyticsEngine(binding) if binding is not None else None)
