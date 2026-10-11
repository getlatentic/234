# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the connectors record about the wallet's money, in Workers Analytics Engine (the METRICS binding,
docs/metrics.md): one data point for each wallet movement, written, repeated or refused. A data point holds
the entry's kind, the outcome and the amount, never the owner or any id. Recording never fails what it
records; a Worker without the binding records nothing."""

import logging
from collections.abc import Sequence
from typing import Any, Protocol

from .money import Kobo

log = logging.getLogger(__name__)

WALLET = "wallet"
WRITTEN, REPEAT, REFUSED = "ok", "repeat", "refused"


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

    def wallet(self, entry_kind: str, outcome: str, amount_kobo: Kobo) -> None:
        """blob2 the entry's kind (fund, spend, release, refund, withdraw, withdraw_back, adjust, and any kind
        the journal gains), blob3 outcome (ok: written now, repeat: an earlier call wrote it, refused: the
        rule kept it out); double1 the amount in kobo."""
        try:
            self._sink.write(WALLET, (entry_kind, outcome), (amount_kobo,))
        except Exception:
            log.warning("A %s data point could not be written", WALLET, exc_info=True)


def metrics_of(env: Any) -> Metrics:
    binding = getattr(env, "METRICS", None)
    return Metrics(AnalyticsEngine(binding) if binding is not None else None)
