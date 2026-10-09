# SPDX-License-Identifier: AGPL-3.0-or-later
"""A page as text: its title and the words of its body, with scripts, styles, menus, forms and frames left
out, and no link kept (the model is given the page's address, not the addresses a page points to)."""

import re
from html.parser import HTMLParser

SKIPPED = frozenset({"script", "style", "noscript", "svg", "template", "nav", "footer", "aside", "form"})
SKIPPED |= frozenset({"iframe", "canvas", "head", "button", "select", "option"})
BREAKS = frozenset(
    {"p", "div", "li", "br", "tr", "section", "article", "ul", "ol", "table", "blockquote", "pre"}
)
BREAKS |= frozenset({"h1", "h2", "h3", "h4", "h5", "h6", "dt", "dd"})
_BLANKS = re.compile("[ \t\r\f\v\xa0]+")
_RUN = re.compile(r"\s+")
_LINES = re.compile(r"\n\s*\n\s*")


class _Reader(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title = ""
        self._skipping = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "title":
            self._in_title = True
        elif tag in SKIPPED:
            self._skipping += 1
        elif tag in BREAKS and not self._skipping:
            self.parts.append("\n\n" if tag.startswith("h") or tag == "p" else "\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        elif tag in SKIPPED and self._skipping:
            self._skipping -= 1
        elif tag in BREAKS and not self._skipping:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        elif not self._skipping:
            self.parts.append(_RUN.sub(" ", data))


def text_of(html: str) -> tuple[str, str]:
    """The page's title and its body text."""
    reader = _Reader()
    reader.feed(html)
    reader.close()
    body = _BLANKS.sub(" ", "".join(reader.parts))
    lines = "\n".join(line.strip() for line in body.splitlines())
    return _BLANKS.sub(" ", reader.title).strip(), _LINES.sub("\n\n", lines).strip()
