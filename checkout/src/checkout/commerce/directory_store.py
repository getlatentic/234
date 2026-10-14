# SPDX-License-Identifier: AGPL-3.0-or-later
"""Reading the directory from D1. Every text another party wrote passes through `third_party` on the way in,
so nothing downstream, a tool result, a quote or a card, holds a control character or an unbounded string."""

import json
import re
from typing import Any

from ..db import Db
from .model import Choice, FieldSpec, Merchant, Offer, OptionGroup
from .text import third_party

NAME_LIMIT = 80
LABEL_LIMIT = 40
DESCRIPTION_LIMIT = 300
OFFER_LIMIT = 100
_WORD = re.compile(r"[^a-z0-9]+")
_STATUS_ORDER = "CASE status WHEN 'live' THEN 0 WHEN 'beta' THEN 1 ELSE 2 END"


def _field(spec: dict[str, Any]) -> FieldSpec:
    return FieldSpec(
        name=spec["name"],
        label=third_party(spec["label"], LABEL_LIMIT),
        kind=spec["kind"],
        required=bool(spec.get("required", True)),
        options=tuple(third_party(option, LABEL_LIMIT) for option in spec.get("options", [])),
        least=int(spec.get("min", 1)),
        most=int(spec.get("max", 120)),
        account=bool(spec.get("account", False)),
    )


def merchant_of(row: dict[str, Any]) -> Merchant:
    return Merchant(
        id=row["id"],
        provider=row["provider"],
        name=third_party(row["name"], NAME_LIMIT),
        category=row["category"],
        status=row["status"],
        requires_link=bool(row["requires_link"]),
        blurb=third_party(row["blurb"], DESCRIPTION_LIMIT),
        min_kobo=row["min_kobo"],
        max_kobo=row["max_kobo"],
        fee_label=third_party(row["fee_label"], LABEL_LIMIT),
        fee_kobo=row["fee_kobo"],
        checks_account=bool(row["checks_account"]),
        fields=tuple(_field(spec) for spec in json.loads(row["fields"])),
    )


def _group(spec: dict[str, Any]) -> OptionGroup:
    return OptionGroup(
        id=spec["id"],
        label=third_party(spec["label"], LABEL_LIMIT),
        least=int(spec["min"]),
        most=int(spec["max"]),
        choices=tuple(
            Choice(c["id"], third_party(c["label"], LABEL_LIMIT), int(c["delta_kobo"]))
            for c in spec["choices"]
        ),
    )


def offer_of(row: dict[str, Any]) -> Offer:
    return Offer(
        merchant_id=row["merchant_id"],
        id=row["id"],
        name=third_party(row["name"], NAME_LIMIT),
        description=third_party(row["description"], DESCRIPTION_LIMIT),
        tags=third_party(row["tags"], 200),
        price_kind=row["price_kind"],
        price_kobo=row["price_kobo"],
        min_kobo=row["min_kobo"],
        max_kobo=row["max_kobo"],
        available=bool(row["available"]),
        max_quantity=row["max_quantity"],
        option_groups=tuple(_group(spec) for spec in json.loads(row["option_groups"])),
    )


class DirectoryStore:
    """The merchants of one provider, and their offers."""

    def __init__(self, db: Db, provider: str) -> None:
        self._db = db
        self._provider = provider

    async def merchants(self, category: str | None = None) -> list[Merchant]:
        rows = await self._db.rows(
            f"SELECT * FROM merchant WHERE provider = ? AND (? IS NULL OR category = ?) "
            f"ORDER BY {_STATUS_ORDER}, name",
            self._provider,
            category,
            category,
        )
        return [merchant_of(row) for row in rows]

    async def merchant(self, merchant_id: str) -> Merchant | None:
        row = await self._db.row(
            "SELECT * FROM merchant WHERE id = ? AND provider = ?", merchant_id, self._provider
        )
        return merchant_of(row) if row else None

    async def offers(self, merchant_id: str, query: str | None = None) -> list[Offer]:
        """A merchant's offers in its own order, those whose name, description or tags hold every word of
        `query` when there is one."""
        words = [word for word in _WORD.split((query or "").lower()) if word]
        conditions = "".join(" AND lower(name || ' ' || description || ' ' || tags) LIKE ?" for _ in words)
        rows = await self._db.rows(
            f"SELECT * FROM offer WHERE merchant_id = ?{conditions} "
            f"ORDER BY position, id LIMIT {OFFER_LIMIT}",
            merchant_id,
            *[f"%{word}%" for word in words],
        )
        return [offer_of(row) for row in rows]

    async def offers_named(self, merchant_id: str, offer_ids: list[str]) -> dict[str, Offer]:
        """The offers with these ids, by id; an id the merchant does not have is not in the answer."""
        marks = ", ".join("?" for _ in offer_ids)
        rows = await self._db.rows(
            f"SELECT * FROM offer WHERE merchant_id = ? AND id IN ({marks})", merchant_id, *offer_ids
        )
        return {offer.id: offer for offer in map(offer_of, rows)}
