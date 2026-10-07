# SPDX-License-Identifier: AGPL-3.0-or-later
"""234 as a person's own agent at other Brands (host turns/reach/): a sub of its own per person and Brand; a
conversation, a delegation and a sign-in that belong to one person; the Brand's interval respected; a sign-in
settled once; a token the Brand refuses dropped; and a receipt kept only when the Brand's published key signed
exactly the claims shown, for 234 and that Brand. Run against the host's own tests."""

from tools.mutations.model import Mutation
from tools.mutations.model import host_mutation as host

REACH = ["tests/test_reach.py"]

MUTATIONS: list[Mutation] = [
    host(
        "reach: a person's sub at a Brand names the Brand",
        "turns/reach/agent.py",
        'f"234-pact-sub\\n{card_url}\\n{owner}"',
        'f"234-pact-sub\\n{owner}"',
        REACH,
    ),
    host(
        "reach: a person's sub at a Brand names the person",
        "turns/reach/agent.py",
        'f"234-pact-sub\\n{card_url}\\n{owner}"',
        'f"234-pact-sub\\n{card_url}"',
        REACH,
    ),
    host(
        "reach: a conversation at a Brand is the person's own",
        "turns/reach/store.py",
        '"SELECT context_id FROM reach_conversation WHERE owner = ? AND brand = ?", owner, brand',
        '"SELECT context_id FROM reach_conversation WHERE ? IS NOT NULL AND brand = ?", owner, brand',
        REACH,
    ),
    host(
        "reach: a delegation at a Brand is the person's own",
        "turns/reach/store.py",
        '"SELECT brand_name, access_token, refresh_token, scopes, expires_at FROM reach_delegation "\n'
        '            "WHERE owner = ? AND brand = ?",',
        '"SELECT brand_name, access_token, refresh_token, scopes, expires_at FROM reach_delegation "\n'
        '            "WHERE ? IS NOT NULL AND brand = ?",',
        REACH,
    ),
    host(
        "reach: a sign-in card is the person's own",
        "turns/reach/store.py",
        '"SELECT * FROM reach_signin WHERE id = ? AND owner = ?", sign_in_id, owner',
        '"SELECT * FROM reach_signin WHERE id = ? AND ? IS NOT NULL", sign_in_id, owner',
        REACH,
    ),
    host(
        "reach: the Brand's token endpoint is asked no faster than its interval",
        "turns/reach/signing_in.py",
        "if now_ms - sign_in.polled_at < sign_in.interval * 1000 or brand.delegation is None:",
        "if brand.delegation is None:",
        REACH,
    ),
    host(
        "reach: a sign-in is settled once, by whatever ended it first",
        "turns/reach/store.py",
        "\"UPDATE reach_signin SET state = ? WHERE id = ? AND state = 'pending' RETURNING id\",",
        '"UPDATE reach_signin SET state = ? WHERE id = ? RETURNING id",',
        REACH,
    ),
    host(
        "reach: a delegation token the Brand refuses is dropped",
        "turns/reach/server.py",
        "        except TokenRejected:\n            await self._store.forget_delegation(owner, brand.id)\n",
        "        except TokenRejected:\n",
        REACH,
    ),
    host(
        "reach: a receipt is kept only when the Brand's published key signed it",
        "turns/reach/receipts.py",
        "if key is None or not jws.signed_by(found, key):",
        "if key is None:",
        REACH,
    ),
    host(
        "reach: a receipt is kept only when the claims shown are the ones signed",
        "turns/reach/receipts.py",
        'if claims != receipt.get("claims") or not all(name in claims for name in CLAIMS):',
        "if not all(name in claims for name in CLAIMS):",
        REACH,
    ),
    host(
        "reach: a receipt is kept only when it names 234 and this Brand",
        "turns/reach/receipts.py",
        'if claims["pa"] != issuer or claims["brand"] != brand.interface_url:',
        'if claims["brand"] != brand.interface_url:',
        REACH,
    ),
    host(
        "reach: an ES256 signature's nonce comes from the key and the message",
        "signatures/ec_key.py",
        "k = hmac.new(k, v + marker + x + h, hashlib.sha256).digest()",
        "k = hmac.new(k, v + marker + h, hashlib.sha256).digest()",
        ["tests/test_signatures.py"],
    ),
]
