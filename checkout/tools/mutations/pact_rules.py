# SPDX-License-Identifier: AGPL-3.0-or-later
"""PACT, the endpoint personal agents reach 234 through: a token signed by a registered, enabled agent's key,
for this host's audience, living at most 300 s; one owner per (agent, sub); a context only for its own User
and Brand; a retried messageId answered from storage; a Brand's chat shown and allowed only its connectors.
And PACT Delegated: a delegation token the host signed, for this Brand, sent by the agent it was issued to,
for the very User its grant was made for; a turn limited to its scopes; a device code bound to its User and
taken once, for the scopes the person left ticked; a refresh token used once; a context that runs as an
account only with that account's token, in a chat the first one's links never open; a receipt signed over
its own claims. Run against the host's own tests."""

from tools.mutations.model import Mutation
from tools.mutations.model import host_mutation as host

PACT = ["tests/test_pact.py", "tests/test_es256.py", "tests/test_jwks.py", "tests/test_scope.py"]
DELEGATED = ["tests/test_pact_delegation.py", "tests/test_permissions.py"]

MUTATIONS: list[Mutation] = [
    host(
        "pact: a token whose signature does not verify is refused",
        "pact/identity.py",
        "    if not good:\n",
        "    if good is None:\n",
        PACT,
    ),
    host(
        "pact: an ES256 signature is checked against its message and key",
        "pact/es256.py",
        "return point[0] * zinv * zinv % P % N == r",
        "return True",
        PACT,
    ),
    host(
        "pact: an ES256 key off the curve is refused",
        "pact/es256.py",
        "if len(signature) != 64 or not on_curve(x, y):",
        "if len(signature) != 64:",
        PACT,
    ),
    host(
        "pact: a token is for this host's audience",
        "pact/identity.py",
        'if claims.get("aud") != audience:',
        "if False:",
        PACT,
    ),
    host(
        "pact: a token lives at most 300 s",
        "pact/identity.py",
        " or exp - iat > MAX_LIFETIME_SECONDS:",
        ":",
        PACT,
    ),
    host(
        "pact: a disabled agent is refused",
        "pact/identity.py",
        "if agent is None or not agent.enabled:",
        "if agent is None:",
        PACT,
    ),
    host(
        "pact: each User of an agent is an owner of their own",
        "pact/identity.py",
        'hashlib.sha256(f"{self.issuer}\\n{self.sub}".encode())',
        "hashlib.sha256(self.issuer.encode())",
        PACT,
    ),
    host(
        "pact: a context continues only for its own User and Brand",
        "pact/conversation.py",
        "Context.objects.filter(chat_id=incoming.context_id, brand=brand.id, owner=caller.owner)",
        "Context.objects.filter(chat_id=incoming.context_id)",
        PACT,
    ),
    host(
        "pact: a repeated messageId is answered from storage, not run again",
        "pact/conversation.py",
        "    if (seen := _claim(context, incoming.message_id)) is not None:",
        "    if (seen := _claim(context, incoming.message_id)) is not None and False:",
        PACT,
    ),
    host(
        "pact: a Brand's chat is made with the Brand's connectors",
        "pact/conversation.py",
        'return Chat.objects.create(owner=owner, connectors=",".join(brand.connectors))',
        "return Chat.objects.create(owner=owner)",
        PACT,
    ),
    host(
        "pact: an unknown key id refetches the agent's keys at most once per cooldown",
        "pact/jwks.py",
        "if found is None and self.clock() - self._fetched >= REFETCH_SECONDS:",
        "if found is None:",
        PACT,
    ),
    host(
        "pact: a Brand's chat calls only its connectors' tools",
        "turns/permissions.py",
        "if not scope.allows(qualified, self.servers):",
        "if False:",
        PACT,
    ),
    host(
        "pact: a Brand's chat is shown only its connectors' tools",
        "turns/permissions.py",
        "return scope.within(shown(tools, self.memory_tools, self.reads_notes), self.servers)",
        "return shown(tools, self.memory_tools, self.reads_notes)",
        PACT,
    ),
    host(
        "pact delegated: a delegation token's signature is verified with the host's key",
        "pact/signing.py",
        'if not rs256.verify(f"{parts[0]}.{parts[1]}".encode(), signature, found.n, found.e):',
        "if False:",
        DELEGATED,
    ),
    host(
        "pact delegated: a delegation token is for this Brand's interface",
        "pact/delegation.py",
        '        and claims.get("aud") == addresses.interface_url(brand)\n',
        "",
        DELEGATED,
    ),
    host(
        "pact delegated: a delegation token's grant was made for the very User of the agent that sends it",
        "pact/delegation.py",
        "pa_owner=caller.owner, account=claims",
        "account=claims",
        DELEGATED,
    ),
    host(
        "pact delegated: a revoked grant's tokens are refused",
        "pact/delegation.py",
        'account=claims["sub"], revoked=False',
        'account=claims["sub"]',
        DELEGATED,
    ),
    host(
        "pact delegated: a call needing a scope the token lacks is refused",
        "turns/permissions.py",
        "if needed is not None and needed not in (self.scopes or ()):",
        "if False:",
        DELEGATED,
    ),
    host(
        "pact delegated: the notes are read for an agent only with memory:read",
        "turns/permissions.py",
        "return self.account and (self.scopes is None or MEMORY_READ in self.scopes)",
        "return self.account",
        DELEGATED,
    ),
    host(
        "pact delegated: a turn's scopes are those of the message that drove it",
        "turns/permissions.py",
        "scopes = frozenset(listed) if isinstance(listed, list) else None",
        "scopes = None",
        DELEGATED,
    ),
    host(
        "pact delegated: a message without a delegation token carries no scopes",
        "pact/conversation.py",
        "scopes = sorted(delegation.scopes) if delegation else []",
        "scopes = sorted(delegation.scopes) if delegation else None",
        DELEGATED,
    ),
    host(
        "pact delegated: a device code answers only the User of the agent that asked for it",
        "pact/device.py",
        "if found is None or found.pa_owner != caller.owner:",
        "if found is None:",
        DELEGATED,
    ),
    host(
        "pact delegated: an approved device code is taken once",
        "pact/device.py",
        '    if not claimed:\n        raise OAuthRefused("invalid_grant", "That device code has been used.")',
        "    pass",
        DELEGATED,
    ),
    host(
        "pact delegated: a grant holds only the scopes the person left ticked",
        "pact/device.py",
        "allowed = [s for s in found.scopes.split() if s in decision.allowed]",
        "allowed = found.scopes.split() if decision.allowed else []",
        DELEGATED,
    ),
    host(
        "pact delegated: a refresh token used twice ends its grant",
        "pact/grants.py",
        "    if not claimed:\n        Grant.objects",
        "    if False:\n        Grant.objects",
        DELEGATED,
    ),
    host(
        "pact delegated: an OAuth call's client_id is the agent's issuer",
        "pact/oauth_views.py",
        'if request.POST.get("client_id") != caller.issuer:',
        "if False:",
        DELEGATED,
    ),
    host(
        "pact delegated: a context that runs as an account needs that account's token",
        "pact/conversation.py",
        "    if found.account:\n",
        "    if False:\n",
        DELEGATED,
    ),
    host(
        "pact delegated: a context begun without delegation moves to a new chat, never giving its own away",
        "pact/conversation.py",
        "    chat = _chat(brand, account)\n",
        "    chat = found.chat\n    Chat.objects.filter(pk=chat.pk).update(owner=account)\n",
        DELEGATED,
    ),
    host(
        "pact delegated: a receipt is signed over its own claims",
        "pact/receipts.py",
        'return {"jws": signing.sign(claims), "claims": claims}',
        'return {"jws": signing.sign({**claims, "scopesUsed": []}), "claims": claims}',
        DELEGATED,
    ),
]
