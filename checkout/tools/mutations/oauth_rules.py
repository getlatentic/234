# SPDX-License-Identifier: AGPL-3.0-or-later
"""The OAuth gateway other MCP clients sign in through: PKCE, a code used once, a token for one connector,
refresh rotation, exact redirects, the owner the host sets itself, and no fetch of an address. Run against
the host's own tests."""

from tools.mutations.model import Mutation
from tools.mutations.model import host_mutation as host

OAUTH = ["tests/test_oauth.py"]

MUTATIONS: list[Mutation] = [
    host(
        "a code is exchanged only with its own PKCE verifier",
        "oauth/grants.py",
        "not VERIFIER.fullmatch(verifier) or not hmac.compare_digest(s256(verifier), found.challenge)",
        "False",
        OAUTH,
    ),
    host(
        "a code works once",
        "oauth/grants.py",
        '"DELETE FROM oauth_code WHERE digest = %s "',
        '"SELECT client_id, owner, redirect_uri, challenge, resource, scope, expires_at FROM oauth_code "\n'
        '        "WHERE digest = %s --"',
        OAUTH,
    ),
    host(
        "a refresh token is used once",
        "oauth/grants.py",
        "WHERE digest = %s AND kind = %s AND used = 0 ",
        "WHERE digest = %s AND kind = %s ",
        OAUTH,
    ),
    host(
        "a refresh token used twice ends its grant",
        "oauth/grants.py",
        "            Token.objects.filter(family=used.family).delete()\n",
        "",
        OAUTH,
    ),
    host(
        "a token opens only the connector it was issued for",
        "oauth/gateway.py",
        "access is None or access.resource != resource_url(connector)",
        "access is None",
        OAUTH,
    ),
    host(
        "a redirect URI must be one the client registered",
        "oauth/requests.py",
        "    if not matches(client.redirect_uris, redirect_uri):",
        "    if False:",
        OAUTH,
    ),
    host(
        "a caller cannot name the owner: the gateway passes on only MCP headers",
        "oauth/gateway.py",
        'PASSED_ON = ("mcp-protocol-version", "mcp-session-id", "last-event-id")',
        'PASSED_ON = ("mcp-protocol-version", "mcp-session-id", "last-event-id", "x-ledger-owner")',
        OAUTH,
    ),
    host(
        "a client metadata document is never fetched from an address",
        "oauth/clients.py",
        '        and not host.replace(".", "").isdigit()',
        "        and True",
        OAUTH,
    ),
]
