# SPDX-License-Identifier: AGPL-3.0-or-later
"""Sealing tokens at rest: what is stored is not the token, it opens only for the owner and the column it was
sealed for, only under the key that sealed it, and any change to it is noticed."""

import pytest

from checkout.commerce.index.secretbox import SealError, SecretBox

CONTEXT = "index-connection\nalice\naccess"
TOKEN = "at-" + "x" * 80


class TestSealing:
    def test_a_sealed_value_opens(self):
        box = SecretBox("a" * 40)
        assert box.open(box.seal(TOKEN, CONTEXT), CONTEXT) == TOKEN

    def test_the_sealed_value_is_not_the_token_and_holds_none_of_it(self):
        sealed = SecretBox("a" * 40).seal(TOKEN, CONTEXT)
        assert TOKEN not in sealed and "xxxxxxxx" not in sealed

    def test_sealing_twice_gives_different_values(self):
        box = SecretBox("a" * 40)
        assert box.seal(TOKEN, CONTEXT) != box.seal(TOKEN, CONTEXT)

    def test_another_key_cannot_open_it(self):
        sealed = SecretBox("a" * 40).seal(TOKEN, CONTEXT)
        with pytest.raises(SealError):
            SecretBox("b" * 40).open(sealed, CONTEXT)

    @pytest.mark.parametrize("other", ["index-connection\nbob\naccess", "index-connection\nalice\nrefresh"])
    def test_another_owner_or_column_cannot_open_it(self, other):
        box = SecretBox("a" * 40)
        with pytest.raises(SealError):
            box.open(box.seal(TOKEN, CONTEXT), other)

    def test_a_changed_value_is_noticed(self):
        box = SecretBox("a" * 40)
        version, nonce, cipher, tag = box.seal(TOKEN, CONTEXT).split(".")
        flipped = ("A" if cipher[0] != "A" else "B") + cipher[1:]
        with pytest.raises(SealError):
            box.open(".".join((version, nonce, flipped, tag)), CONTEXT)

    @pytest.mark.parametrize("junk", ["", "v1", "v1.a.b", "v2.a.b.c", "not.sealed.at.all", "v1.!.!.!"])
    def test_a_value_that_is_not_sealed_is_refused(self, junk):
        with pytest.raises(SealError):
            SecretBox("a" * 40).open(junk, CONTEXT)

    def test_a_long_value_and_an_empty_one_both_round_trip(self):
        box = SecretBox("a" * 40)
        for value in ("", "é" * 500, "t" * 5000):
            assert box.open(box.seal(value, CONTEXT), CONTEXT) == value
