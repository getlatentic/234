# SPDX-License-Identifier: AGPL-3.0-or-later
import pytest
from django.test import Client

from chat.models import Chat

pytestmark = pytest.mark.django_db


def cookie_of(client: Client) -> str:
    return client.cookies["visitor"].value


def test_the_first_visit_sets_a_signed_http_only_cookie_and_it_is_kept():
    client = Client()
    client.get("/")
    first = cookie_of(client)
    morsel = client.cookies["visitor"]
    assert morsel["httponly"] and morsel["samesite"] == "Lax" and int(morsel["max-age"]) > 86400
    client.get("/")
    assert cookie_of(client) == first


def test_a_forged_or_edited_cookie_is_replaced_by_a_new_visitor():
    client = Client()
    client.get("/")
    good = cookie_of(client)
    client.cookies["visitor"] = "f" * 32
    client.get("/")
    assert cookie_of(client) != "f" * 32
    assert cookie_of(client) != good
    client.cookies["visitor"] = good + "x"
    client.get("/")
    assert cookie_of(client) != good + "x"


def test_chats_belong_to_the_visitor_who_made_them(visitor):
    other = Client()
    mine = visitor.new_chat()
    assert Chat.objects.get(pk=mine).owner.startswith("v:")
    assert other.get(f"/c/{mine}/").status_code == 404
    assert visitor.client.get(f"/c/{mine}/").status_code == 200


def test_the_list_shows_only_my_chats_newest_activity_first(visitor):
    first, second = visitor.new_chat(), visitor.new_chat()
    Chat.objects.create(owner="v:someone-else")
    page = visitor.client.get("/").content.decode()
    assert page.count('/delete" data-confirm') == 2
    assert page.index(second) < page.index(first)


def test_a_share_link_lets_another_visitor_in_and_it_expires(visitor, settings):
    chat_id = visitor.new_chat()
    link = visitor.post(f"/c/{chat_id}/share").json()["url"]
    guest = Client()
    assert guest.get(f"/c/{chat_id}/").status_code == 404
    landed = guest.get(link.removeprefix("http://testserver"))
    assert landed.status_code == 302 and landed["Location"] == f"/c/{chat_id}/"
    assert guest.get(f"/c/{chat_id}/").status_code == 200
    assert chat_id in guest.get("/").content.decode()
    assert guest.get("/join/not-a-token").status_code == 410


def test_only_the_owner_deletes_a_chat_and_its_log_goes_with_it(visitor, backend):
    chat_id = visitor.new_chat()
    link = visitor.post(f"/c/{chat_id}/share").json()["url"].removeprefix("http://testserver")
    guest = Client()
    guest.get(link)
    token = visitor.token()
    assert guest.post(f"/c/{chat_id}/delete", HTTP_X_CSRFTOKEN=token).status_code == 403
    assert visitor.post(f"/c/{chat_id}/delete").status_code == 302
    assert backend.erased == [chat_id] and not Chat.objects.filter(pk=chat_id).exists()


def test_no_cookie_names_a_domain_so_none_is_sent_to_the_sandbox_or_anywhere_else_but_the_host():
    client = Client()
    client.get("/")
    assert client.cookies["visitor"]["domain"] == ""
    assert all(morsel["domain"] == "" for morsel in client.cookies.values())
