# SPDX-License-Identifier: AGPL-3.0-or-later
"""A passage is quoted as data: what a page carries that could steer or mislead is taken out, and every line
of it is shown behind a `>` so nothing in it can pass for a line of ours.

Out go markup, invisible and direction-changing characters, and any link whose host is not on the allow-list
(a markdown link keeps its words)."""

import re

from .allowlist import check_domain

LINK_REMOVED = "[link removed]"

_TAG = re.compile(r"</?[A-Za-z!][^>]*>")
_INVISIBLE = re.compile("[​-‏‪-‮⁠-⁩﻿\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_MARKDOWN_LINK = re.compile(r"\[([^\]]*)\]\(\s*([^)\s]*)[^)]*\)")
_BARE_LINK = re.compile(r"(?:https?://|www\.)[^\s<>()\"']+", re.IGNORECASE)


def _markdown_link(match: re.Match[str]) -> str:
    words, url = match.group(1), match.group(2)
    return f"{words} ({url})" if check_domain(url) else words


def _bare_link(match: re.Match[str]) -> str:
    url = match.group().rstrip(".,;:")
    return match.group().replace(url, url if check_domain(url) else LINK_REMOVED, 1)


def clean(text: str) -> str:
    text = _INVISIBLE.sub("", _TAG.sub("", text))
    return _BARE_LINK.sub(_bare_link, _MARKDOWN_LINK.sub(_markdown_link, text))


def quoted(text: str) -> str:
    return "\n".join(f"> {line}" if line.strip() else ">" for line in clean(text).strip().splitlines())
