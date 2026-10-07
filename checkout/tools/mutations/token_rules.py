# SPDX-License-Identifier: AGPL-3.0-or-later
"""The host's verification of a Firebase ID token: which algorithm, whose signature, whose claims, which
keys, and the settings that keep an unsigned token out of a public deployment. Run against the host's own
tests (`tests/test_firebase_token.py`, and the settings tests that start the host in a process)."""

from tools.mutations.model import Mutation
from tools.mutations.model import host_mutation as host

TOKEN = ["tests/test_firebase_token.py"]
PUBLIC = [
    "tests/test_auth_config.py::test_a_development_only_setting_stops_the_host_outside_development",
    "tests/test_auth_config.py::test_the_public_configuration_refuses_an_emulator_token_even_when_sign_in_is_on",
    "tests/test_auth_config.py::test_a_value_that_goes_into_the_policy_must_be_a_host",
    "tests/test_auth_config.py::test_sign_in_needs_all_four_values_and_an_account_key_is_never_defaulted_in_production",
    "tests/test_auth_config.py::test_cross_origin_opener_policy_allows_the_popup_only_where_sign_in_exists",
]
ENDPOINTS = ["tests/test_accounts.py"]


def claim(guardrail: str, find: str, replace: str) -> Mutation:
    return host(guardrail, "accounts/firebase_token.py", find, replace, TOKEN)


MUTATIONS: list[Mutation] = [
    claim(
        "only the emulator's tokens may be unsigned",
        'if algorithm == "none" and emulator:',
        'if algorithm == "none":',
    ),
    claim(
        "an unsigned emulator token carries no signature",
        "        if parts[2]:\n",
        "        if False:\n",
    ),
    claim(
        "an algorithm that is not RS256 is refused before any key is looked at",
        'raise InvalidToken(f"algorithm {algorithm!r} is not accepted")',
        "pass",
    ),
    claim(
        "a token's signature must verify against Google's key",
        "if not rs256.verify(signing_input, raw, *key):",
        "if False:",
    ),
    claim(
        "the token's issuer is this Firebase project",
        'if claims.get("iss") != f"https://securetoken.google.com/{project}":',
        "if False:",
    ),
    claim(
        "the token's audience is this Firebase project",
        'if claims.get("aud") != project:',
        "if False:",
    ),
    claim("an expired token is refused", "if exp < now - SKEW_SECONDS:", "if False:"),
    claim(
        "a token issued in the future is refused",
        "if iat > now + SKEW_SECONDS or auth_time > now + SKEW_SECONDS:",
        "if False:",
    ),
    claim(
        "a token that lives longer than an hour is refused",
        "if exp - iat > MAX_LIFE_SECONDS:",
        "if False:",
    ),
    claim(
        "a token without a subject is refused",
        "if not isinstance(uid, str) or not uid or len(uid) > 128:",
        "if False:",
    ),
    claim(
        "an email Google has not verified is refused",
        ' or claims.get("email_verified") is not True',
        "",
    ),
    claim(
        "only a Google sign-in is accepted",
        'if not isinstance(firebase, dict) or firebase.get("sign_in_provider") != PROVIDER:',
        "if not isinstance(firebase, dict):",
    ),
    claim(
        "a token of unreasonable size is refused before it is parsed",
        "not 0 < len(token) <= MAX_TOKEN_CHARS or",
        "",
    ),
    host(
        "a signature's padding is rebuilt and compared whole, not parsed",
        "signatures/rs256.py",
        "return hmac.compare_digest(block, padded(message, size))",
        "return block.endswith(hashlib.sha256(message).digest())",
        TOKEN,
    ),
    host(
        "a public key under 2048 bits is refused",
        "signatures/rs256.py",
        "modulus.bit_length() < MIN_MODULUS_BITS",
        "False",
        TOKEN,
    ),
    host(
        "an unknown key id makes at most one fetch a minute",
        "accounts/keys.py",
        "if found is None and self.clock() - self._fetched >= REFETCH_SECONDS:",
        "if found is None:",
        TOKEN,
    ),
    host(
        "Google's keys are kept only as long as Google says",
        "accounts/keys.py",
        "self._expires = self._fetched + _max_age(headers)",
        "self._expires = float('inf')",
        TOKEN,
    ),
    host(
        "the emulator's tokens are accepted only where an emulator host is configured",
        "accounts/service.py",
        "emulator=bool(settings.FIREBASE_AUTH_EMULATOR_HOST),",
        "emulator=True,",
        [*PUBLIC, *ENDPOINTS],
    ),
    host(
        "an emulator host stops the server outside development",
        "config/settings.py",
        "if (FIREBASE_AUTH_EMULATOR_HOST or FIREBASE_KEYS_URL != GOOGLE_KEYS_URL) and (",
        "if (FIREBASE_KEYS_URL != GOOGLE_KEYS_URL) and (",
        PUBLIC,
    ),
    host(
        "a stand-in for Google's keys stops the server outside development",
        "config/settings.py",
        "if (FIREBASE_AUTH_EMULATOR_HOST or FIREBASE_KEYS_URL != GOOGLE_KEYS_URL) and (",
        "if (FIREBASE_AUTH_EMULATOR_HOST) and (",
        PUBLIC,
    ),
    host(
        "a deployment that requires an owner is never a development one",
        "config/settings.py",
        '    not DEBUG or runtime.get_bool("REQUIRE_OWNER")\n',
        "    not DEBUG\n",
        PUBLIC,
    ),
    host(
        "the auth domain that goes into the page's policy is a host name",
        "config/settings.py",
        'if not re.fullmatch(r"[a-z0-9.-]*", FIREBASE_AUTH_DOMAIN):',
        "if False:",
        PUBLIC,
    ),
    host(
        "the emulator address that goes into the page's policy is host:port",
        "config/settings.py",
        'if not re.fullmatch(r"[a-z0-9.:-]*", FIREBASE_AUTH_EMULATOR_HOST):',
        "if False:",
        PUBLIC,
    ),
    host(
        "a production account key is never a default",
        "config/settings.py",
        'runtime.get("ACCOUNT_KEY", _INSECURE_DEV_KEY if DEBUG else "")',
        'runtime.get("ACCOUNT_KEY", _INSECURE_DEV_KEY)',
        PUBLIC,
    ),
    host(
        "sign-in exists only when all of its settings are given",
        "config/settings.py",
        "SIGN_IN_ENABLED = all((",
        "SIGN_IN_ENABLED = any((",
        PUBLIC,
    ),
    host(
        "the popup's window link is kept only where sign-in exists",
        "config/settings.py",
        '"same-origin-allow-popups" if SIGN_IN_ENABLED else "same-origin"',
        '"same-origin-allow-popups"',
        PUBLIC,
    ),
]
