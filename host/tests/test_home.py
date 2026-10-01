# SPDX-License-Identifier: AGPL-3.0-or-later
import re

import pytest

from chat.palette import GROUND, PRIMARY
from chat.starters import STARTERS

pytestmark = pytest.mark.django_db

CHATS_BUTTON = re.compile(r"<button[^>]*data-action=\"chats\"[^>]*>")


def chats_button(html: str) -> str:
    return CHATS_BUTTON.search(html).group(0)


def test_the_empty_home_has_a_wordmark_one_line_and_the_starters_in_that_order(visitor):
    body = visitor.client.get("/").content.decode().split("<body", 1)[1]
    order = [
        body.index(marker)
        for marker in ('data-slot="wordmark"', 'data-slot="tagline"', 'data-slot="pill"', "<chat-starters")
    ]
    assert order == sorted(order)
    tagline = re.search(r'data-slot="tagline">([^<]+)</p>', body).group(1)
    assert tagline.count(".") == 1 and tagline.endswith(".") and "approve every payment" in tagline


def test_every_starter_is_a_real_button_with_its_message_and_an_icon(visitor):
    body = visitor.client.get("/").content.decode()
    group = body.split("<chat-starters", 1)[1].split("</chat-starters>", 1)[0]
    assert group.count("<button") == len(STARTERS)
    for starter in STARTERS:
        assert f'type="button" data-text="{starter.text}"' in group
        assert f'<span class="min-w-0 wrap-anywhere">{starter.label}</span>' in group
    assert group.count("<svg") == len(STARTERS) and 'aria-hidden="true"' in group


def test_a_starter_that_needs_the_person_is_marked_to_fill_and_the_others_are_not(visitor):
    body = visitor.client.get("/").content.decode()
    buttons = re.findall(r"<button type=\"button\" data-text=\"([^\"]*)\"( data-fill)? ", body)
    assert [(text, bool(fill)) for text, fill in buttons] == [(s.text, not s.sends) for s in STARTERS]


def test_the_chats_button_is_hidden_until_the_visitor_has_a_chat(visitor):
    assert " hidden" in chats_button(visitor.client.get("/").content.decode())
    assert (
        "data-chats"
        not in visitor.client.get("/").content.decode().split("<chat-thread", 1)[1].split(">", 1)[0]
    )
    visitor.new_chat()
    home = visitor.client.get("/").content.decode()
    assert " hidden" not in chats_button(home)
    assert "data-chats" in home.split("<chat-thread", 1)[1].split(">", 1)[0]


def test_the_chats_button_is_a_round_button_at_the_top_left_outside_the_composer(visitor):
    html = visitor.client.get("/").content.decode()
    button = chats_button(html)
    assert "fixed" in button and "left-[max(0.75rem,env(safe-area-inset-left))]" in button
    assert (
        "top-[max(0.75rem,env(safe-area-inset-top))]" in button
        and "size-11" in button
        and "rounded-full" in button
    )
    assert html.index(button) < html.index("<chat-composer")


def test_the_browser_and_the_manifest_take_their_colour_from_the_palette(visitor):
    html = visitor.client.get("/").content.decode()
    assert f'content="{GROUND["light"]}" media="(prefers-color-scheme: light)"' in html
    assert f'content="{GROUND["dark"]}" media="(prefers-color-scheme: dark)"' in html
    manifest = visitor.client.get("/manifest.webmanifest").json()
    assert manifest["background_color"] == GROUND["light"]
    assert manifest["theme_color"] == PRIMARY == "#03492f"


def test_the_model_settings_are_read_once_however_many_pages_are_shown(visitor, monkeypatch):
    from chat.views import pages

    reads = []
    monkeypatch.setattr(pages.runtime, "get", lambda name, default=None: reads.append(name) or default)
    pages.turn_settings.cache_clear()
    try:
        for _ in range(3):
            assert visitor.client.get("/").status_code == 200
        assert len(reads) == len(set(reads)) > 0
    finally:
        pages.turn_settings.cache_clear()


def test_the_home_says_so_when_no_model_is_configured(visitor, monkeypatch):
    from chat.views import pages

    monkeypatch.setattr(pages.runtime, "get", lambda name, default=None: default)
    pages.turn_settings.cache_clear()
    try:
        body = visitor.client.get("/").content.decode()
    finally:
        pages.turn_settings.cache_clear()
    assert "No model is configured" in body
