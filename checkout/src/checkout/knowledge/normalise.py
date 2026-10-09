# SPDX-License-Identifier: AGPL-3.0-or-later
"""Folding for search: a person types "ọkọ̀ owner" or "kudin lasisi" without the marks the page has. Both the
indexed text and the query go through `fold`, so they meet.

Yoruba and Igbo marks (dots below, tone marks) are combining characters and are dropped; Hausa's hooked
letters (ɓ ɗ ƙ ƴ) are letters of their own and fold to their plain forms."""

import re
import unicodedata

_HAUSA = str.maketrans({"ɓ": "b", "Ɓ": "b", "ɗ": "d", "Ɗ": "d", "ƙ": "k", "Ƙ": "k", "ƴ": "y", "Ƴ": "y"})
_APOSTROPHES = re.compile("[\u2019\u2018\u02bc`\u00b4']")
_SPACES = re.compile(r"\s+")


def fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text.translate(_HAUSA))
    bare = "".join(c for c in decomposed if not unicodedata.combining(c))
    return _SPACES.sub(" ", _APOSTROPHES.sub("", bare).casefold()).strip()
