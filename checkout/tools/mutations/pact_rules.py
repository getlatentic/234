# SPDX-License-Identifier: AGPL-3.0-or-later
"""PACT, the endpoint personal agents reach 234 through: a token signed by a registered, enabled agent's key,
for this host's audience, living at most 300 s; one owner per (agent, sub); a context only for its own User
and Brand; a retried messageId answered from storage; a Brand's chat shown and allowed only its connectors.
Run against the host's own tests."""

from tools.mutations.model import Mutation
from tools.mutations.model import host_mutation as host

PACT = ["tests/test_pact.py", "tests/test_es256.py", "tests/test_jwks.py", "tests/test_scope.py"]

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
        'Chat.objects.create(owner=caller.owner, connectors=",".join(brand.connectors))',
        "Chat.objects.create(owner=caller.owner)",
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
        "turns/runner.py",
        'if not scope.allows(call["name"], self._servers):',
        "if False:",
        PACT,
    ),
    host(
        "pact: a Brand's chat is shown only its connectors' tools",
        "turns/runner.py",
        "tools = scope.within(offered(await self._hub.model_tools(), self._owner), self._servers)",
        "tools = offered(await self._hub.model_tools(), self._owner)",
        PACT,
    ),
]
