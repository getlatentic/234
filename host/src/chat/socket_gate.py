# SPDX-License-Identifier: AGPL-3.0-or-later
"""Who may open a chat's WebSocket, decided from the request alone so the Worker can answer the upgrade
before Django: the address names one chat, the ticket (minted by Django for a visitor who may see it)
must be for that chat and fresh, and the page that opens it must be this site."""

import re
from urllib.parse import parse_qs, urlsplit

from . import tickets

SOCKET_PATH = re.compile(r"^/c/(?P<chat_id>[0-9a-f]{32})/ws$")


def chat_for_socket(url: str, origin: str | None) -> str | None:
    parts = urlsplit(url)
    found = SOCKET_PATH.match(parts.path)
    if found is None or origin is None or urlsplit(origin).netloc != parts.netloc:
        return None
    ticket = parse_qs(parts.query).get("ticket", [""])[0]
    return found["chat_id"] if tickets.chat_for_ws_ticket(ticket) == found["chat_id"] else None
