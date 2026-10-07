# SPDX-License-Identifier: AGPL-3.0-or-later
"""Connected apps: a person sees and ends only what they allowed themselves, and ending it works at once. Run
against the host's own tests."""

from tools.mutations.model import Mutation
from tools.mutations.model import host_mutation as host

CONNECTED = ["tests/test_connected.py"]

MUTATIONS: list[Mutation] = [
    host(
        "connected apps: a person sees only the apps they allowed",
        "oauth/grants.py",
        'Token.objects.filter(owner=owner, expires_at__gte=_now(now)).values_list("client_id", "resource")',
        'Token.objects.filter(expires_at__gte=_now(now)).values_list("client_id", "resource")',
        CONNECTED,
    ),
    host(
        "connected apps: a person ends only their own grants to an app",
        "oauth/grants.py",
        "    Token.objects.filter(owner=owner, client_id=client_id).delete()",
        "    Token.objects.filter(client_id=client_id).delete()",
        CONNECTED,
    ),
    host(
        "connected apps: disconnecting an app ends its tokens",
        "oauth/grants.py",
        "    Token.objects.filter(owner=owner, client_id=client_id).delete()",
        "    pass",
        CONNECTED,
    ),
    host(
        "connected apps: a person sees only the agents they allowed",
        "pact/grants.py",
        "Grant.objects.filter(account=account, revoked=False, expires_at__gt=now)",
        "Grant.objects.filter(revoked=False, expires_at__gt=now)",
        CONNECTED,
    ),
    host(
        "connected apps: a person ends only their own agent grants",
        "pact/grants.py",
        "    Grant.objects.filter(id=grant_id, account=account).update(revoked=True)",
        "    Grant.objects.filter(id=grant_id).update(revoked=True)",
        CONNECTED,
    ),
    host(
        "connected apps: ending an agent grant drops its refresh tokens",
        "pact/grants.py",
        "    RefreshToken.objects.filter(grant_id=grant_id, grant__account=account).delete()",
        "    pass",
        CONNECTED,
    ),
    host(
        "connected apps: only a signed-in person has connected apps",
        "accounts/connected.py",
        "    if account is None:\n        raise Http404",
        "    if account is None:\n        return ''",
        CONNECTED,
    ),
    host(
        "connected apps: a person is told when a Brand did not revoke",
        "accounts/connected.py",
        "    if held is None or revoked:",
        "    if True:",
        CONNECTED,
    ),
    host(
        "connected apps: a Brand is asked to revoke only what the person holds there",
        "accounts/connected.py",
        "    revoked = held is not None and get_backend().end_brand(owner, brand)",
        "    revoked = get_backend().end_brand(owner, brand)",
        CONNECTED,
    ),
]
