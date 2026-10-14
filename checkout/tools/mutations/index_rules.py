# SPDX-License-Identifier: AGPL-3.0-or-later
"""A person's own Paystack Index account (docs/commerce.md, the `index` provider; commerce/index/): tokens sealed
for their owner and column and opened by no other; a sign-in state taken once, by its own person, in time; PKCE
and only Index's own hosts; a token renewed before it runs out and on 401, once at a time, and a refused refresh
asking the person to connect again; what Index lists kept to what 234 can buy, in 234's words, for accounts
only; limits and Zap checked before a quote; a preview that cannot spend; one send per quote; an Index quote
approved as that and no other way; a failed order that is not a refund. The host's side runs against the host's
tests."""

from tools.mutations.model import SRC, Mutation
from tools.mutations.model import host_mutation as host

BOX = ["tests/test_index_secretbox.py"]
TOKENS = ["tests/test_index_tokens.py"]
CONNECT = ["tests/test_index_connect.py"]
MERCHANTS = ["tests/test_index_merchants.py"]
QUOTES = ["tests/test_index_quotes.py"]
FULFIL = ["tests/test_index_fulfil.py"]
INVARIANTS = ["tests/test_index_invariants.py"]
READING = ["tests/test_index_reading.py"]
SETTINGS = ["tests/test_index_settings.py"]
HOST_TESTS = ["tests/test_connect_index.py"]
INDEX = f"{SRC}/commerce/index"


def index(name: str, file: str, find: str, replace: str, tests: list[str]) -> Mutation:
    return Mutation(f"index: {name}", f"{INDEX}/{file}", find, replace, tests)


def core(name: str, file: str, find: str, replace: str, tests: list[str]) -> Mutation:
    return Mutation(f"index: {name}", f"{SRC}/{file}", find, replace, tests)


MUTATIONS: list[Mutation] = [
    index(
        "a sealed token that was changed is noticed",
        "secretbox.py",
        "if version != VERSION or not hmac.compare_digest(tag, self._tag(context, nonce, cipher)):",
        "if version != VERSION:",
        BOX,
    ),
    index(
        "a sealed token opens only for the context it was sealed for",
        "secretbox.py",
        'purpose + b"\\0" + context.encode()',
        'purpose + b"\\0"',
        BOX,
    ),
    index(
        "a token is sealed for its owner",
        "store.py",
        'return f"index-connection\\n{owner}\\n{column}"',
        'return f"index-connection\\n{column}"',
        TOKENS,
    ),
    index(
        "a sign-in state is the person's own",
        "attempts.py",
        "\"SELECT * FROM index_attempt WHERE state_hash = ? AND owner = ? AND status = 'open' \"",
        "\"SELECT * FROM index_attempt WHERE state_hash = ? AND ? IS NOT NULL AND status = 'open' \"",
        CONNECT,
    ),
    index(
        "a sign-in state runs out",
        "attempts.py",
        "\"AND step = 'authorize' AND expires_at > ?\",",
        "\"AND step = 'authorize' AND ? IS NOT NULL\",",
        CONNECT,
    ),
    index(
        "a sign-in state is taken once",
        "attempts.py",
        '"UPDATE index_attempt SET state_hash = NULL, verifier_sealed = NULL, updated_at = ? "',
        '"UPDATE index_attempt SET state_hash = state_hash, verifier_sealed = verifier_sealed, updated_at = ? "',
        CONNECT,
    ),
    index(
        "the sign-in asks for S256 PKCE",
        "oauth.py",
        '"code_challenge_method": "S256",',
        '"code_challenge_method": "plain",',
        CONNECT,
    ),
    index(
        "the code challenge is the SHA-256 of the verifier",
        "oauth.py",
        "digest = hashlib.sha256(verifier.encode()).digest()",
        "digest = hashlib.sha1(verifier.encode()).digest()",
        READING,
    ),
    index(
        "an endpoint in Index's metadata must be on a trusted host",
        "oauth.py",
        "if not isinstance(url, str) or origin_of(url) not in self._trusted:",
        "if not isinstance(url, str):",
        READING,
    ),
    index("a token is renewed before it runs out", "tokens.py", "EARLY_MS = 60_000", "EARLY_MS = 0", TOKENS),
    index(
        "a 401 renews the token and tries once more",
        "tokens.py",
        "        except IndexUnauthorized:\n            current = await self.connection(owner)",
        "        except ZeroDivisionError:\n            current = await self.connection(owner)",
        TOKENS,
    ),
    index(
        "a refresh Index refuses ends the connection",
        "tokens.py",
        "        except TokenRefused:\n            await self._store.forget(found.owner)\n            raise reconnect() from None",
        "        except TokenRefused:\n            raise reconnect() from None",
        TOKENS,
    ),
    index(
        "one call at a time refreshes a connection",
        "store.py",
        '"AND (refreshing_at IS NULL OR refreshing_at <= ?)",',
        '"AND ? IS NOT NULL",',
        TOKENS,
    ),
    index(
        "disconnecting forgets the tokens",
        "accounts.py",
        "            await self._store.forget(owner)\n            revoked = await self._revoked(connection)",
        "            revoked = await self._revoked(connection)",
        TOKENS,
    ),
    index(
        "one client is registered for a deployment",
        "registrations.py",
        "        if found is not None:\n            return found",
        "        if False:\n            return found",
        CONNECT,
    ),
    index(
        "only live and beta merchants are kept",
        "catalog.py",
        "if bought is None or status not in KEPT_STATUSES:",
        "if bought is None:",
        MERCHANTS,
    ),
    index(
        "an id Index gives is a plain slug or the merchant is dropped",
        "catalog.py",
        'if not isinstance(raw, dict) or not is_index_id(raw.get("id")):',
        "if not isinstance(raw, dict):",
        MERCHANTS,
    ),
    index(
        "a visitor is shown no Index merchant",
        "provider.py",
        "        if account_of_call() is None:\n            return []",
        "        if False:\n            return []",
        MERCHANTS,
    ),
    index(
        "a merchant needs the person's connection first",
        "merchants.py",
        "needs_link = not connected or (entry.asks_link and entry.index_id not in linked)",
        "needs_link = entry.asks_link and entry.index_id not in linked",
        MERCHANTS + QUOTES,
    ),
    index(
        "a card links a phone at most a few times",
        "attempts.py",
        "MAX_TRIES = 6",
        "MAX_TRIES = 600",
        MERCHANTS,
    ),
    index(
        "a phone goes to Index in international form",
        "linking.py",
        'return "+234" + normalise_phone(phone)[1:]',
        "return phone",
        MERCHANTS,
    ),
    index(
        "234's cap for a kind is under Index's bound",
        "bounds.py",
        "return least, max(least, min(most, settings.caps_kobo.get(kind, most)))",
        "return least, most",
        SETTINGS + QUOTES,
    ),
    index(
        "Index's address must be https on its own hosts",
        "settings.py",
        'if parts.scheme != "https" or parts.hostname not in ALLOWED_HOSTS or not plain:',
        'if parts.scheme != "https" or not plain:',
        SETTINGS,
    ),
    index(
        "the daily and per-payment limits are checked before Index is asked",
        "provider.py",
        "await self._ledger.assert_quotable(basket.amount_kobo)",
        "pass",
        QUOTES,
    ),
    index(
        "an airtime number is read as a Nigerian number",
        "kind_airtime.py",
        'phone = normalise_phone(basket.fields["phone"])',
        'phone = basket.fields["phone"]',
        QUOTES,
    ),
    index(
        "an order is quoted only when Zap is linked",
        "purchase.py",
        'if data.get("zap_linked") is not True:',
        "if False:",
        QUOTES,
    ),
    index("an order is quoted only when Zap covers it", "purchase.py", "if zap + credits < total:", "if False:", QUOTES),
    index(
        "a meter's holder must be the one the person confirmed",
        "kind_electricity.py",
        "if _holder(reply).casefold() != check.holder_name.casefold():",
        "if False:",
        QUOTES,
    ),
    index(
        "a food order is for one restaurant",
        "kind_food.py",
        "if len(vendors) != 1 or any(",
        "if len(vendors) < 1 or any(",
        QUOTES,
    ),
    index(
        "a food quote is Index's own total",
        "kind_food.py",
        'total = need_kobo(data, "the order\'s total", "grand_total", "total")',
        "total = sum(line.total_kobo for line in lines)",
        QUOTES,
    ),
    index(
        "a preview cannot carry confirmed",
        "purchase.py",
        "if SPENDS in arguments:",
        "if False:",
        INVARIANTS,
    ),
    index(
        "the placing of a two-phase order carries confirmed",
        "purchase.py",
        "return {**self.arguments, SPENDS: True} if self.two_phase else dict(self.arguments)",
        "return dict(self.arguments)",
        FULFIL + INVARIANTS,
    ),
    index(
        "an order is sent at most once",
        "fulfil.py",
        "if not await self._ledger.set_progress_once(quote.id, SENT, {\"at\": self._clock.now()}):",
        "if False:",
        FULFIL,
    ),
    index(
        "a Chowdeck price that moved is not charged",
        "fulfil.py",
        'if purchase.kind == "food" and await self._moved(purchase, owner) != quote.amount_kobo:',
        "if False:",
        FULFIL,
    ),
    index(
        "an answer that never came is pending, not sent again",
        "fulfil.py",
        "        except IndexUnreachable, IndexMisread:\n            self._audit.log",
        "        except IndexMisread:\n            self._audit.log",
        FULFIL,
    ),
    index(
        "an order no debit shows for ends as failed after an hour",
        "following.py",
        "if now - sent_at >= WINDOW_MS else",
        "if False else",
        FULFIL,
    ),
    index(
        "a status Index words in a way 234 does not know is pending",
        "outcomes.py",
        'return named(status) or "pending"',
        'return named(status) or "delivered"',
        READING,
    ),
    core(
        "an order Index failed is a failure, not a refund owed",
        "flows/merchant_leg.py",
        'case "failed" | "reversed" if is_external(quote):',
        'case "failed" | "reversed" if False:',
        FULFIL,
    ),
    core(
        "an Index quote is approved as that and no other way",
        "flows/merchants.py",
        'if (funding == "external") != is_external(quote):',
        "if False:",
        FULFIL,
    ),
    core(
        "the claim of an externally paid quote holds that it is one",
        "flows/merchants.py",
        "\"json_extract(quotes.details, '$.funding') = 'external'\",",
        '"1",',
        FULFIL,
    ),
    core(
        "an Index quote is not approved after the person disconnected",
        "flows/merchants.py",
        "if self.ctx.index is not None and not await self.ctx.index.provider.connected():",
        "if False:",
        FULFIL,
    ),
    core(
        "the approval is bound to where the money comes from",
        "commerce/binding.py",
        'terms["funding"], terms["index"] = d["funding"], d["index"]',
        "pass",
        FULFIL,
    ),
    core(
        "an Index quote offers no wallet",
        "flows/wallet_leg.py",
        'if ctx.wallet is None or quote.state != "open" or is_external(quote):',
        'if ctx.wallet is None or quote.state != "open":',
        QUOTES,
    ),
    core(
        "the card's external approval is not a checkout approval",
        "connectors/kit.py",
        "view = await flow.approve_external(*terms)",
        "view = await flow.approve(*terms)",
        FULFIL,
    ),
    core(
        "connecting is for signed-in accounts",
        "connectors/merchant_accounts.py",
        '    if account_of_call() is None:\n        raise DomainError("ACCOUNT_ONLY", ACCOUNT_ONLY)',
        '    if False:\n        raise DomainError("ACCOUNT_ONLY", ACCOUNT_ONLY)',
        CONNECT,
    ),
    host(
        "index: a guest cannot pay from the owner's Index account",
        "chat/views/cards.py",
        'if server == MERCHANTS_SERVER and (arguments.get("funding") == "external" or "card_id" in arguments):',
        'if server == MERCHANTS_SERVER and ("card_id" in arguments):',
        HOST_TESTS,
    ),
    host(
        "index: a guest cannot press the owner's connect card",
        "chat/views/cards.py",
        'if server == MERCHANTS_SERVER and (arguments.get("funding") == "external" or "card_id" in arguments):',
        'if server == MERCHANTS_SERVER and (arguments.get("funding") == "external"):',
        HOST_TESTS,
    ),
    host(
        "index: a connect card's state reaches every tab",
        "turns/card_calls.py",
        '_STATE_KEYS = ("quote", "memory", "sign_in", "connection")',
        '_STATE_KEYS = ("quote", "memory", "sign_in")',
        HOST_TESTS,
    ),
    host(
        "index: the sign-in callback acts only for a signed-in account",
        "chat/views/connect.py",
        "    if request.account is None:",
        "    if False:",
        HOST_TESTS,
    ),
    host(
        "index: the sign-in callback is rate limited",
        "chat/views/connect.py",
        'if not get_backend().rate_ok(f"connect-index:{request.account.owner}"):',
        "if False:",
        HOST_TESTS,
    ),
]
