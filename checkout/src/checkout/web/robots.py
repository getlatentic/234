# SPDX-License-Identifier: AGPL-3.0-or-later
"""What a site's robots.txt allows (RFC 9309): a file that is missing or refused (4xx) allows everything; a
server that fails (5xx) or does not answer allows nothing."""

from urllib.robotparser import RobotFileParser

AGENT = "234bot"


def allows(status: int | None, text: str, url: str) -> bool:
    if status is None or status >= 500:
        return False
    if status >= 400 or not text.strip():
        return True
    parser = RobotFileParser()
    parser.parse(text.splitlines())
    return parser.can_fetch(AGENT, url)
