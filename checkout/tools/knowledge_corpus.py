# SPDX-License-Identifier: AGPL-3.0-or-later
"""The government guidance corpus (docs/knowledge.md): one Markdown file per source in knowledge/sources, its
front matter, the rules a source must meet, and the rows it becomes.

A source is an excerpt or a paraphrase of a page, never the page. It is 'published' only with a reviewer,
and each fee on it is checked by a second person."""

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import yaml

from checkout.knowledge.allowlist import check_domain
from checkout.knowledge.chunker import chunk
from checkout.knowledge.normalise import fold

SOURCES = Path(__file__).resolve().parents[2] / "knowledge" / "sources"
CONTENT_TYPES = ("guidance", "fee", "procedure", "notice", "form")
STATUSES = ("draft", "published", "retired")
BODY_LIMIT = 6000
STALE_AFTER = timedelta(days=180)
_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_FRONT = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.DOTALL)


@dataclass(frozen=True)
class Source:
    path: Path
    meta: dict[str, Any]
    body: str
    problems: list[str] = field(default_factory=list)

    @property
    def id(self) -> str:
        return str(self.meta.get("id", ""))


def parse(path: Path) -> Source:
    found = _FRONT.match(path.read_text())
    if found is None:
        return Source(path, {}, "", ["no front matter between --- lines"])
    try:
        meta = yaml.safe_load(found.group(1)) or {}
    except yaml.YAMLError as error:
        return Source(path, {}, found.group(2), [f"front matter is not YAML: {error}"])
    if not isinstance(meta, dict):
        return Source(path, {}, found.group(2), ["front matter is not a mapping"])
    source = Source(path, meta, found.group(2).strip("\n"))
    source.problems.extend(problems_of(source))
    return source


def _day(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _required(meta: dict[str, Any]) -> list[str]:
    keys = (
        "id",
        "agency",
        "title",
        "url",
        "content_type",
        "language",
        "trust_tier",
        "status",
        "retrieved_at",
    )
    return [f"{key} is missing" for key in keys if meta.get(key) in (None, "")]


def _shape(source: Source, today: date) -> list[str]:
    meta, out = source.meta, []
    if not _ID.match(source.id) or source.id != source.path.stem:
        out.append("id is lowercase words joined by hyphens and is the file's name")
    if meta["content_type"] not in CONTENT_TYPES:
        out.append(f"content_type is one of {', '.join(CONTENT_TYPES)}")
    if meta["status"] not in STATUSES:
        out.append(f"status is one of {', '.join(STATUSES)}")
    if meta["trust_tier"] not in (1, 2, 3):
        out.append("trust_tier is 1, 2 or 3")
    if not check_domain(str(meta["url"])):
        out.append("url is an https link on the allow-list")
    elif meta["trust_tier"] == 1 and not str(meta["url"]).split("/")[2].endswith(".gov.ng"):
        out.append("tier 1 is an official .gov.ng page")
    if (retrieved := _day(meta["retrieved_at"])) is None or retrieved > today:
        out.append("retrieved_at is a date that is not in the future")
    return out


def _keywords(source: Source) -> list[str]:
    keywords = source.meta.get("keywords")
    if keywords is None:
        return []
    if not isinstance(keywords, list) or not all(isinstance(k, str) and k.strip() for k in keywords):
        return ["keywords is a list of words and phrases"]
    return [] if len(keywords) <= 20 else ["keywords has at most 20 entries"]


def _published(source: Source) -> list[str]:
    meta, out = source.meta, []
    if meta["status"] != "published":
        return out
    if not meta.get("reviewed_by") or _day(meta.get("reviewed_at")) is None:
        out.append("a published source has reviewed_by and reviewed_at")
    for fee in meta.get("fees") or []:
        out.extend(_fee(fee, source))
    return out


def _fee(fee: dict[str, Any], source: Source) -> list[str]:
    item, naira = fee.get("item"), fee.get("naira")
    if not item or not isinstance(naira, int) or naira < 0:
        return ["a fee has an item and a whole-naira amount"]
    out = []
    if not fee.get("verified_by") or fee["verified_by"] == source.meta.get("reviewed_by"):
        out.append(f"fee '{item}' is verified by someone other than the reviewer")
    if f"{naira:,}" not in source.body:
        out.append(f"fee '{item}' ({naira:,}) is not in the text")
    return out


def problems_of(source: Source, today: date | None = None) -> list[str]:
    today = today or date.today()
    if missing := _required(source.meta):
        return missing
    out = _shape(source, today) + _keywords(source) + _published(source)
    if not source.body.strip():
        out.append("the text is empty")
    elif len(source.body) > BODY_LIMIT:
        out.append(f"the text is over {BODY_LIMIT} characters: keep an excerpt or a paraphrase, not the page")
    return out


def load_all(root: Path = SOURCES) -> list[Source]:
    sources = [parse(p) for p in sorted(root.rglob("*.md")) if p.name != "README.md"]
    seen: dict[str, Path] = {}
    for source in sources:
        if source.id and source.id in seen:
            source.problems.append(f"id is also used by {seen[source.id].name}")
        seen.setdefault(source.id, source.path)
    return sources


def is_stale(source: Source, today: date | None = None) -> bool:
    retrieved = _day(source.meta.get("retrieved_at"))
    return retrieved is None or (today or date.today()) - retrieved > STALE_AFTER


def rows_of(source: Source) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    meta = source.meta
    digest = hashlib.sha256((source.path.read_text()).encode()).hexdigest()[:16]
    row = {
        **{
            k: meta.get(k) for k in ("id", "agency", "title", "url", "content_type", "language", "trust_tier")
        },
        "status": meta["status"],
        "retrieved_at": str(meta["retrieved_at"]),
        "published_at": str(meta["published_at"]) if meta.get("published_at") else None,
        "reviewed_by": meta.get("reviewed_by"),
        "reviewed_at": str(meta["reviewed_at"]) if meta.get("reviewed_at") else None,
        "checksum": digest,
    }
    keywords = " ".join(str(k) for k in meta.get("keywords") or [])
    passages = [
        {
            "id": f"{source.id}#{order}",
            "ord": order,
            "start_offset": p.start,
            "end_offset": p.end,
            "text": p.text,
            "folded": fold(f"{p.text} {keywords}"),
        }
        for order, p in enumerate(chunk(source.body))
    ]
    return row, passages
