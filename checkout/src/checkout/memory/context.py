# SPDX-License-Identifier: AGPL-3.0-or-later
from dataclasses import dataclass

from ..audit import Audit
from ..clock import Clock
from ..paystack.api import PaystackApi
from .proposals import Proposals
from .store import MemoryStore


@dataclass(frozen=True)
class MemoryContext:
    """What every memory operation needs, passed in so the Worker and the tests wire the same code."""

    store: MemoryStore
    proposals: Proposals
    paystack: PaystackApi
    audit: Audit
    clock: Clock
