# SPDX-License-Identifier: AGPL-3.0-or-later
"""The text of an entry as it is stored: one line for a title and a hook, a few lines for a body, with no
control, bidirectional or invisible characters, no backticks, and no square brackets in a title (the index
writes a title between two). Every length is a refusal, not a cut, so the person is never shown a title that
differs from the one saved."""

import re
import unicodedata

from ..errors import DomainError

TITLE_MAX = 60
HOOK_MAX = 120
_BRACKETS = str.maketrans({"[": "(", "]": ")", "`": "'"})
_BLANK_LINES = re.compile(r"\n{3,}")


def _visible(text: str, keep_newlines: bool) -> str:
    normal = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
    kept = []
    for char in normal:
        if char == "\n" and keep_newlines:
            kept.append(char)
        elif char in "\n\t" or unicodedata.category(char) in ("Zs", "Zl", "Zp"):
            kept.append(" ")
        elif unicodedata.category(char)[0] != "C":
            kept.append(char)
    return "".join(kept)


def _line(text: str, name: str, longest: int) -> str:
    cleaned = " ".join(_visible(text, False).translate(_BRACKETS).split())
    if not cleaned or len(cleaned) > longest:
        raise DomainError("MEMORY_INVALID", f"{name} must be 1 to {longest} characters.")
    return cleaned


def clean_title(value: str) -> str:
    return _line(value, "title", TITLE_MAX)


def clean_hook(value: str) -> str:
    return _line(value, "hook", HOOK_MAX)


def clean_body(value: str, max_bytes: int, required: bool = True) -> str:
    lines = [" ".join(line.split()) for line in _visible(value, True).translate(_BRACKETS).split("\n")]
    cleaned = _BLANK_LINES.sub("\n\n", "\n".join(lines)).strip()
    if required and not cleaned:
        raise DomainError("MEMORY_INVALID", "body must not be empty.")
    if len(cleaned.encode()) > max_bytes:
        raise DomainError(
            "MEMORY_INVALID", f"body is over {max_bytes} bytes. Keep a note short, or split it in two."
        )
    return cleaned


def clean_name(value: str, longest: int = 80) -> str:
    """A name the bank gave, as one line. One longer than `longest` is cut: it is not the person's text."""
    cleaned = " ".join(_visible(value, False).translate(_BRACKETS).split())[:longest].strip()
    if not cleaned:
        raise DomainError("PROVIDER_ERROR", "The bank returned no account name.")
    return cleaned
