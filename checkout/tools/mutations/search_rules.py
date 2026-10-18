# SPDX-License-Identifier: AGPL-3.0-or-later
"""What keeps web search safe and cheap (checkout web/search.py, search_budget.py, settings.py): the key goes
as a bearer and only to DeepSeek's host over https, the query is cut to what the API takes, an unsafe address
in a result is dropped, a date that is not an ISO day is not a publication day, a failed call is a refusal,
a person's day is capped in one statement, and the same question is asked once an hour."""

from tools.mutations.model import Mutation

SEARCH = ["tests/test_web_search.py"]


def checkout(name: str, path: str, old: str, new: str) -> Mutation:
    return Mutation(name, path, old, new, SEARCH)


S = "src/checkout/web/search.py"

MUTATIONS: list[Mutation] = [
    checkout(
        "search: the key is sent as a bearer",
        S,
        '"authorization": f"Bearer {self._api_key}",',
        '"authorization": self._api_key,',
    ),
    checkout("search: the query is cut to what the API takes", S, "query[:QUERY_CHARS].rstrip()", "query"),
    checkout(
        "search: the count is between one and ten", S, "limit = max(1, min(limit, MAX_RESULTS))", "pass"
    ),
    checkout("search: the client names itself", S, '"user-agent": USER_AGENT,\n', ""),
    checkout(
        "search: the key goes only to DeepSeek's host",
        S,
        "parts.hostname != HOST or ",
        "",
    ),
    checkout("search: only https", S, 'parts.scheme != "https" or ', ""),
    checkout("search: no credentials in the address", S, " or parts.username", ""),
    checkout(
        "search: an unsafe address in a result is dropped", S, "if safe_url.problem(url) is None:", "if True:"
    ),
    checkout(
        "search: a date that is not an ISO day is not a publication day",
        S,
        "return found.group() if found else None",
        'return found.group() if found else str(value or "") or None',
    ),
    checkout("search: a snippet is cut", S, "return snippet[:SNIPPET_CHARS]", "return snippet"),
    checkout(
        "search: a thin snippet gives way to the summary",
        S,
        "if len(snippet) >= THIN_SNIPPET_CHARS:",
        "if True:",
    ),
    checkout(
        "search: a refused or throttled call (402, 429, 5xx) is not an answer",
        S,
        "if not reply.ok:",
        "if reply.status >= 500:",
    ),
    checkout(
        "search: a reply without a list of results is not an answer",
        S,
        "if not isinstance(items, list):",
        "if items is None:",
    ),
    checkout(
        "search: a query is held to what the API takes before it is counted",
        "src/checkout/connectors/web.py",
        "max_length=QUERY_CHARS",
        "max_length=100_000",
    ),
    checkout(
        "search: a key with a space is not used",
        "src/checkout/web/settings.py",
        "if not _KEY_SHAPE.fullmatch(key):",
        "if False:",
    ),
    checkout(
        "search: a person's day is capped in one statement",
        "src/checkout/web/search_budget.py",
        "WHERE used < ?",
        "WHERE ? > 0",
    ),
    checkout(
        "search: a search is counted before it is made",
        "src/checkout/connectors/web.py",
        'if not await self._budget.take(current_owner() or ""):',
        "if False:",
    ),
    checkout(
        "search: the same question within the hour is not asked again",
        "src/checkout/connectors/web.py",
        "        if cached is not None:\n",
        "        if False:\n",
    ),
    checkout(
        "search: without the key search is off",
        "src/checkout/web/settings.py",
        "if trouble(read) or not _text(read, KEY):",
        "if trouble(read):",
    ),
    checkout(
        "search: the connector offers search only when it is set up",
        "src/checkout/connectors/web.py",
        "tools=(fetch, found) if search else (fetch,),",
        "tools=(fetch, found),",
    ),
]
