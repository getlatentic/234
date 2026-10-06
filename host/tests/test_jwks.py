# SPDX-License-Identifier: AGPL-3.0-or-later
import json

from pact.jwks import REFETCH_SECONDS, KeySet


def document(*kids: str) -> bytes:
    keys = [{"kid": kid, "kty": "RSA", "n": "AQAB", "e": "AQAB"} for kid in kids]
    return json.dumps({"keys": keys}).encode()


class Agent:
    def __init__(self, *kids: str):
        self.kids, self.fetches = kids, 0

    def fetch(self, url: str):
        self.fetches += 1
        return 200, {"cache-control": "max-age=3600"}, document(*self.kids)


def test_a_rotated_key_is_fetched_once_the_cooldown_has_passed_and_not_before():
    now = [1000.0]
    agent = Agent("old")
    keys = KeySet("https://pa.example/jwks.json", agent.fetch, lambda: now[0])
    assert keys.get("old") is not None and agent.fetches == 1
    agent.kids = ("new",)
    now[0] += REFETCH_SECONDS - 1
    assert keys.get("new") is None and agent.fetches == 1
    now[0] += 1
    assert keys.get("new") is not None and agent.fetches == 2


def test_random_key_ids_make_at_most_one_fetch_per_cooldown():
    now = [1000.0]
    agent = Agent("k1")
    keys = KeySet("https://pa.example/jwks.json", agent.fetch, lambda: now[0])
    keys.get("k1")
    now[0] += REFETCH_SECONDS
    for n in range(50):
        assert keys.get(f"random-{n}") is None
    assert agent.fetches == 2


def test_keys_are_fetched_again_when_their_cache_life_ends():
    now = [1000.0]
    agent = Agent("k1")
    keys = KeySet("https://pa.example/jwks.json", agent.fetch, lambda: now[0])
    keys.get("k1")
    now[0] += 3600
    keys.get("k1")
    assert agent.fetches == 2
