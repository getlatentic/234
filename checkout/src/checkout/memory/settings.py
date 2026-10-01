# SPDX-License-Identifier: AGPL-3.0-or-later
"""The limits memory runs under: what one owner may keep, how large the index may grow, how long a forgotten
entry can still be brought back."""

from collections.abc import Callable
from dataclasses import dataclass

from ..errors import ConfigError

DAY_MS = 24 * 60 * 60 * 1000


@dataclass(frozen=True)
class MemorySettings:
    index_tokens: int = 1_500
    max_entries: int = 200
    max_body_bytes: int = 2_048
    retention_days: int = 30
    proposal_ttl_seconds: int = 86_400
    max_pending: int = 10

    @property
    def retention_ms(self) -> int:
        return self.retention_days * DAY_MS

    @classmethod
    def from_env(cls, read: Callable[[str], str | None]) -> MemorySettings:
        base = cls()
        return cls(
            index_tokens=_positive(read, "MEMORY_INDEX_TOKENS", base.index_tokens),
            max_entries=_positive(read, "MEMORY_MAX_ENTRIES", base.max_entries),
            max_body_bytes=_positive(read, "MEMORY_MAX_BODY_BYTES", base.max_body_bytes),
            retention_days=_positive(read, "MEMORY_RETENTION_DAYS", base.retention_days),
            proposal_ttl_seconds=_positive(read, "MEMORY_PROPOSAL_TTL_SECONDS", base.proposal_ttl_seconds),
            max_pending=_positive(read, "MEMORY_MAX_PENDING", base.max_pending),
        )


def _positive(read: Callable[[str], str | None], name: str, fallback: int) -> int:
    raw = (read(name) or "").strip()
    if not raw:
        return fallback
    if not raw.isdecimal() or int(raw) <= 0:
        raise ConfigError(f'{name} must be a positive whole number, got "{raw}".')
    return int(raw)
