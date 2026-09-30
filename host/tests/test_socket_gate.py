# SPDX-License-Identifier: AGPL-3.0-or-later
import pytest

from chat import tickets
from chat.socket_gate import chat_for_socket

CHAT = "a" * 32
OTHER = "b" * 32
ORIGIN = "https://checkout.example"


def url(chat=CHAT, ticket=None, host="checkout.example"):
    ticket = tickets.mint_ws_ticket(CHAT) if ticket is None else ticket
    return f"https://{host}/c/{chat}/ws?ticket={ticket}"


def test_a_ticket_for_this_chat_from_this_site_opens_it():
    assert chat_for_socket(url(), ORIGIN) == CHAT


@pytest.mark.parametrize(
    "case",
    [
        dict(ticket="nonsense"),
        dict(ticket=""),
        dict(chat=OTHER),
        dict(host="checkout.example:8443"),
    ],
)
def test_a_wrong_ticket_or_chat_or_site_opens_nothing(case):
    assert chat_for_socket(url(**case), ORIGIN) is None


def test_a_page_from_another_site_or_none_opens_nothing():
    assert chat_for_socket(url(), "https://evil.example") is None
    assert chat_for_socket(url(), None) is None


def test_an_expired_ticket_opens_nothing(monkeypatch):
    ticket = tickets.mint_ws_ticket(CHAT)
    monkeypatch.setattr(tickets, "WS_TTL_SECONDS", -1)
    assert chat_for_socket(url(ticket=ticket), ORIGIN) is None


def test_a_share_token_is_not_a_socket_ticket():
    assert chat_for_socket(url(ticket=tickets.mint_share_token(CHAT)), ORIGIN) is None


def test_the_path_must_be_a_chat_socket():
    assert chat_for_socket(f"https://checkout.example/c/{CHAT}/events?ticket=x", ORIGIN) is None
