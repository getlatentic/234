# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the model is shown of a passage: its text cleaned and quoted, and where it came from (link, date,
tier). A link that is not on the allow-list is not shown, whatever the source row says."""

from typing import Any

from .allowlist import check_domain
from .sanitise import clean, quoted

TIERS = {1: "official", 2: "agency partner", 3: "reputable outlet"}


def passage_view(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "passage_id": row["passage_id"],
        "source_id": row["source_id"],
        "title": clean(row["title"]),
        "agency": row["agency"],
        "content_type": row["content_type"],
        "trust_tier": row["trust_tier"],
        "url": row["url"] if check_domain(row["url"]) else None,
        "retrieved_at": row["retrieved_at"],
        "published_at": row["published_at"],
        "text": clean(row["text"]).strip(),
    }


def source_view(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_id": row["id"],
        "agency": row["agency"],
        "title": clean(row["title"]),
        "url": row["url"] if check_domain(row["url"]) else None,
        "content_type": row["content_type"],
        "trust_tier": row["trust_tier"],
        "language": row["language"],
        "retrieved_at": row["retrieved_at"],
        "passages": row["passages"],
    }


def passages_text(views: list[dict[str, Any]]) -> str:
    """Each passage under a header line of ours and quoted below it; nothing inside a quote is ours."""
    blocks = []
    for number, view in enumerate(views, 1):
        where = f"{view['url'] or 'no link'}, retrieved {view['retrieved_at']}, {TIERS[view['trust_tier']]}"
        header = f"[{number}] {view['title']} ({view['agency']}; {where}); id {view['passage_id']}"
        blocks.append(f"{header}\n{quoted(view['text'])}")
    return "\n\n".join(blocks) if blocks else "No source says anything about that."
