# SPDX-License-Identifier: AGPL-3.0-or-later
"""The person's own view of what 234 remembers: it exists for a signed-in account and for nobody else, every
change goes to the memory connector for the account's own key, and a guest of a shared chat cannot change the
owner's notes from a card."""

import json

import pytest
from django.test import Client

from accounts.owner import account_owner
from chat.models import Access
from turns.hub import HubError

from .account_support import ACCOUNT_KEY, Device

pytestmark = pytest.mark.django_db

ENTRY = "0123456789abcdef"
PAGES = (
    ("get", "/memory/"),
    ("get", "/memory/export.json"),
    ("post", f"/memory/{ENTRY}/edit"),
    ("post", f"/memory/{ENTRY}/forget"),
    ("post", "/memory/undo"),
    ("post", "/memory/delete-all"),
)


def reach(device: Device, how: str, path: str, body: dict | None = None):
    return device.client.get(path) if how == "get" else device.post(path, body)


@pytest.fixture
def ada(sign_in_on, key, backend):
    device = Device()
    assert device.sign_in(key).status_code == 200
    backend.owner = account_owner("uid-abc", ACCOUNT_KEY)
    return device


@pytest.mark.parametrize(("how", "path"), PAGES)
def test_nobody_who_is_not_signed_in_reaches_any_of_it(sign_in_on, backend, how, path):
    assert reach(Device(), how, path).status_code == 404
    assert backend.memory_calls == []


@pytest.mark.parametrize(("how", "path"), PAGES)
def test_a_site_without_sign_in_has_none_of_it(client, backend, how, path):
    if how == "get":
        assert client.get(path).status_code == 404
    else:
        token = client.get("/").content.decode().split('csrf-token" content="')[1].split('"')[0]
        assert (
            client.post(path, "{}", content_type="application/json", HTTP_X_CSRFTOKEN=token).status_code
            == 404
        )
    assert backend.memory_calls == []


def test_the_list_is_what_the_connector_says_for_the_accounts_own_chat_owner(ada, backend):
    backend.memory_answers["list_memories"] = {
        "structuredContent": {"entries": [{"id": ENTRY}], "limit": 200}
    }
    answer = ada.client.get("/memory/")
    assert answer.status_code == 200 and answer.json() == {"entries": [{"id": ENTRY}], "limit": 200}
    assert backend.memory_calls == [(backend.owner, "list_memories", {})]


def test_a_title_and_a_hook_are_changed_by_the_connector_and_only_text_is_passed_on(ada, backend):
    answer = ada.post(
        f"/memory/{ENTRY}/edit", {"title": "Mummy", "hook": 7, "owner": "u:" + "00" * 16, "x": 1}
    )
    assert answer.status_code == 200
    assert backend.memory_calls == [(backend.owner, "edit_memory", {"id": ENTRY, "title": "Mummy"})]


def test_an_id_that_is_not_an_entry_id_is_not_a_page(ada, backend):
    assert ada.post("/memory/not-an-id/edit", {"title": "x"}).status_code == 404
    assert ada.post("/memory/../forget", {}).status_code == 404
    assert backend.memory_calls == []


def test_forgetting_gives_the_page_what_it_needs_to_undo(ada, backend):
    answer = {"structuredContent": {"proposal_id": "f" * 16, "token": "t0k", "title": "Mum"}}
    backend.memory_answers["forget_memory"] = answer
    done = ada.post(f"/memory/{ENTRY}/forget")
    assert done.json() == answer["structuredContent"]
    assert backend.memory_calls == [(backend.owner, "forget_memory", {"id": ENTRY})]


def test_undo_passes_the_proposal_and_its_token_to_the_connector(ada, backend):
    ada.post("/memory/undo", {"proposal_id": "f" * 16, "token": "t0k", "owner": "x"})
    arguments = {"proposal_id": "f" * 16, "confirm_token": "t0k"}
    assert backend.memory_calls == [(backend.owner, "undo_memory", arguments)]


def test_the_copy_is_a_json_file_to_download_that_is_not_kept_by_a_cache(ada, backend):
    backend.memory_answers["export_memories"] = {"structuredContent": {"entries": [{"title": "Ọmọ"}]}}
    answer = ada.client.get("/memory/export.json")
    assert answer["Content-Disposition"] == 'attachment; filename="234-memory.json"'
    assert answer["Cache-Control"] == "no-store" and answer["Content-Type"] == "application/json"
    assert json.loads(answer.content) == {"entries": [{"title": "Ọmọ"}]} and "Ọmọ" in answer.content.decode()


def test_deleting_everything_is_the_connectors_call_for_the_accounts_key(ada, backend):
    assert ada.post("/memory/delete-all").status_code == 200
    assert backend.memory_calls == [(backend.owner, "delete_all_memories", {})]


def test_a_refusal_of_the_connector_is_a_plain_sentence_with_a_400(ada, backend):
    text = "MEMORY_NOT_FOUND: There is no such note. Check the index for its id."
    backend.memory_answers["edit_memory"] = {"isError": True, "content": [{"type": "text", "text": text}]}
    answer = ada.post(f"/memory/{ENTRY}/edit", {"title": "x"})
    assert answer.status_code == 400 and answer.json() == {
        "error": "There is no such note. Check the index for its id."
    }


def test_a_connector_that_cannot_be_reached_is_a_502_with_one_line(ada, backend):
    def broken(*_):
        raise HubError("down")

    backend.memory = broken
    answer = ada.client.get("/memory/")
    assert answer.status_code == 502 and answer.json() == {"error": "Memory could not be reached. Try again."}


def test_a_change_needs_the_pages_csrf_token(ada, backend):
    strict = Client(enforce_csrf_checks=True)
    strict.cookies = ada.client.cookies
    assert strict.post("/memory/delete-all", "{}", content_type="application/json").status_code == 403
    assert backend.memory_calls == []


@pytest.mark.parametrize(
    "path", ["/memory/undo", "/memory/delete-all", f"/memory/{ENTRY}/edit", f"/memory/{ENTRY}/forget"]
)
def test_a_change_is_never_made_by_a_get(ada, backend, path):
    assert ada.client.get(path).status_code == 405 and backend.memory_calls == []


def test_the_drawer_offers_what_234_remembers_to_an_account_and_to_nobody_else(ada, sign_in_on):
    page = ada.client.get("/").content.decode()
    assert "What 234 remembers" in page and 'data-url="/memory/"' in page and "/memory/export.json" in page
    assert (
        page.index('data-slot="email"')
        < page.index("What 234 remembers")
        < page.index('data-action="sign-out"')
    )
    for other in (Device().client.get("/").content.decode(),):
        assert "What 234 remembers" not in other and "chat-memory" not in other


def test_a_site_without_sign_in_says_nothing_of_memory(client):
    page = client.get("/").content.decode()
    assert "remember" not in page.lower() and "chat-memory" not in page


def test_a_guest_of_a_shared_chat_cannot_change_the_owners_notes_from_a_card(ada, sign_in_on, backend):
    chat = ada.chat()
    guest = Device()
    guest.client.get("/")
    from chat.models import Chat

    Access.objects.create(chat=Chat.objects.get(pk=chat), visitor=guest.client.get("/").wsgi_request.owner)
    body = {
        "server": "memory",
        "name": "confirm_memory",
        "arguments": {"proposal_id": ENTRY, "confirm_token": "t"},
    }
    refused = guest.post(f"/c/{chat}/call", body)
    assert refused.status_code == 403 and "Only the owner of this chat" in refused.json()["error"]
    assert [c for c in backend.submitted if c[1] == "card_call"] == []
    allowed = ada.post(f"/c/{chat}/call", body)
    assert allowed.status_code == 200
    assert [c[2:4] for c in backend.submitted if c[1] == "card_call"] == [("memory", "confirm_memory")]
    other = guest.post(f"/c/{chat}/call", {**body, "server": "send-money", "name": "approve_quote"})
    assert other.status_code == 200
