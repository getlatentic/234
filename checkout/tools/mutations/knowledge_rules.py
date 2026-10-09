# SPDX-License-Identifier: AGPL-3.0-or-later
"""The rules the answers from sources stand on (checkout knowledge/, tools/knowledge_corpus.py): only
published sources are served, the allow-list refuses look-alikes, a link off the list and markup never
reach the model, and a fee needs a second reviewer."""

from tools.mutations.model import Mutation

SEARCH = ["tests/test_knowledge.py"]
CORPUS = ["tests/test_knowledge_corpus.py"]


def checkout(name: str, path: str, old: str, new: str, tests: list[str]) -> Mutation:
    return Mutation(name, path, old, new, tests)


MUTATIONS: list[Mutation] = [
    checkout(
        "knowledge: only a published source is searched",
        "src/checkout/knowledge/store.py",
        "_PUBLISHED = \"s.status = 'published'\"",
        '_PUBLISHED = "1 = 1"',
        SEARCH,
    ),
    checkout(
        "knowledge: a look-alike of a government host is refused",
        "src/checkout/knowledge/allowlist.py",
        "(host.endswith(GOVERNMENT_SUFFIX) and len(host) > len(GOVERNMENT_SUFFIX))",
        '("gov.ng" in host)',
        SEARCH,
    ),
    checkout(
        "knowledge: a link needs https",
        "src/checkout/knowledge/allowlist.py",
        'parts.scheme != "https" or ',
        "",
        SEARCH,
    ),
    checkout(
        "knowledge: a link with credentials is refused",
        "src/checkout/knowledge/allowlist.py",
        "parts.username is not None or parts.password is not None",
        "False",
        SEARCH,
    ),
    checkout(
        "knowledge: a link off the list is removed from a passage",
        "src/checkout/knowledge/sanitise.py",
        '    return f"{words} ({url})" if check_domain(url) else words',
        '    return f"{words} ({url})"',
        SEARCH,
    ),
    checkout(
        "knowledge: markup is taken out of a passage",
        "src/checkout/knowledge/sanitise.py",
        'text = _INVISIBLE.sub("", _TAG.sub("", text))',
        'text = _INVISIBLE.sub("", text)',
        SEARCH,
    ),
    checkout(
        "knowledge: every line of a passage is quoted",
        "src/checkout/knowledge/sanitise.py",
        'f"> {line}" if line.strip() else ">"',
        "line",
        SEARCH,
    ),
    checkout(
        "knowledge: a source link off the list is not shown",
        "src/checkout/knowledge/render.py",
        '"url": row["url"] if check_domain(row["url"]) else None,\n        "retrieved_at": row["ret',
        '"url": row["url"],\n        "retrieved_at": row["ret',
        SEARCH,
    ),
    checkout(
        "knowledge: a search term is quoted so a question is never syntax",
        "src/checkout/knowledge/store.py",
        '" OR ".join(f\'"{w}"\' for w in dict.fromkeys(words[:MAX_TERMS]))',
        '" OR ".join(dict.fromkeys(words[:MAX_TERMS]))',
        SEARCH,
    ),
    checkout(
        "knowledge: a question is folded like the text",
        "src/checkout/knowledge/store.py",
        "words = [w for w in _WORD.findall(fold(query))",
        "words = [w for w in _WORD.findall(query.casefold())",
        SEARCH,
    ),
    checkout(
        "knowledge: the Hausa hooked letters fold to plain ones",
        "src/checkout/knowledge/normalise.py",
        'str.maketrans({"ɓ": "b",',
        'str.maketrans({"ɓ": "ɓ",',
        SEARCH,
    ),
    checkout(
        "knowledge: a fee is verified by someone other than the reviewer",
        "tools/knowledge_corpus.py",
        'or fee["verified_by"] == source.meta.get("reviewed_by")',
        "",
        CORPUS,
    ),
    checkout(
        "knowledge: a fee must be in the text",
        "tools/knowledge_corpus.py",
        'if f"{naira:,}" not in source.body:',
        "if False:",
        CORPUS,
    ),
    checkout(
        "knowledge: a published source needs a reviewer",
        "tools/knowledge_corpus.py",
        'if not meta.get("reviewed_by") or _day(meta.get("reviewed_at")) is None:',
        "if False:",
        CORPUS,
    ),
]
