# SPDX-License-Identifier: AGPL-3.0-or-later
"""What keeps web search safe and cheap (checkout web/search.py, search_budget.py, sigv4.py, settings.py):
the request is signed over its body, only a gateway in the region is called, an unsafe address in a result is
dropped, a person's day is capped in one statement, and the same question is asked once an hour."""

from tools.mutations.model import Mutation

SEARCH = ["tests/test_web_search.py", "tests/test_sigv4.py"]


def checkout(name: str, path: str, old: str, new: str) -> Mutation:
    return Mutation(name, path, old, new, SEARCH)


MUTATIONS: list[Mutation] = [
    checkout(
        "search: the request is signed over its body",
        "src/checkout/web/sigv4.py",
        '[method, parts.path or "/", parts.query, canonical_headers, listed, _sha256(body)]',
        '[method, parts.path or "/", parts.query, canonical_headers, listed, _sha256(b"")]',
    ),
    checkout(
        "search: the secret signs and is not sent",
        "src/checkout/web/sigv4.py",
        "_signing_key(credentials.secret_access_key, day, region, service)",
        "_signing_key(credentials.access_key_id, day, region, service)",
    ),
    checkout(
        "search: only a gateway in the region is called",
        "src/checkout/web/search.py",
        '        or not (parts.hostname or "").endswith(suffix)\n',
        "",
    ),
    checkout(
        "search: only https",
        "src/checkout/web/search.py",
        '        parts.scheme != "https"\n        or not',
        "        not",
    ),
    checkout(
        "search: an unsafe address in a result is dropped",
        "src/checkout/web/search.py",
        "if safe_url.problem(url) is None:",
        "if True:",
    ),
    checkout(
        "search: a snippet is cut",
        "src/checkout/web/search.py",
        'str(item.get("text", ""))[:SNIPPET_CHARS],',
        'str(item.get("text", "")),',
    ),
    checkout(
        "search: the host header is not sent",
        "src/checkout/web/search.py",
        'headers={k: v for k, v in signed.items() if k != "host"},',
        "headers=signed,",
    ),
    checkout(
        "search: a failed gateway call is not an answer",
        "src/checkout/web/search.py",
        'if not isinstance(result, dict) or result.get("isError"):',
        "if not isinstance(result, dict):",
    ),
    checkout(
        "search: after a failure the next search shakes hands again",
        "src/checkout/web/search.py",
        "        except DomainError:\n            self._ready = False\n            raise",
        "        except DomainError:\n            raise",
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
        "search: part of the settings is not enough",
        "src/checkout/web/settings.py",
        "if trouble(read) or not all(_text(read, name) for name in NAMES):",
        "if trouble(read):",
    ),
    checkout(
        "search: the connector offers search only when it is set up",
        "src/checkout/connectors/web.py",
        "tools=(fetch, found) if search else (fetch,),",
        "tools=(fetch, found),",
    ),
]
