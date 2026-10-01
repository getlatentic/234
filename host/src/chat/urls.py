# SPDX-License-Identifier: AGPL-3.0-or-later
from django.urls import path, re_path

from .views import cancel, cards, compact, events, hooks, memory, pages, send, socket

app_name = "chat"

CHAT = r"^c/(?P<chat_id>[0-9a-f]{32})/"

urlpatterns = [
    path("", pages.home, name="index"),
    path("manifest.webmanifest", pages.manifest, name="manifest"),
    path("hooks/payment", hooks.payment, name="payment-hook"),
    path("join/<str:token>", pages.join, name="join"),
    path("memory/", memory.entries, name="memory"),
    path("memory/export.json", memory.export, name="memory-export"),
    path("memory/undo", memory.undo, name="memory-undo"),
    path("memory/delete-all", memory.delete_everything, name="memory-delete-all"),
    re_path(r"^memory/(?P<entry_id>[0-9a-f]{16})/edit$", memory.edit, name="memory-edit"),
    re_path(r"^memory/(?P<entry_id>[0-9a-f]{16})/forget$", memory.forget, name="memory-forget"),
    re_path(CHAT + r"$", pages.page, name="page"),
    re_path(CHAT + r"delete$", pages.delete, name="delete"),
    re_path(CHAT + r"share$", pages.share, name="share"),
    re_path(CHAT + r"start$", send.start, name="start"),
    re_path(CHAT + r"send$", send.send, name="send"),
    re_path(CHAT + r"cancel$", cancel.cancel, name="cancel"),
    re_path(CHAT + r"compact$", compact.compact, name="compact"),
    re_path(CHAT + r"message$", send.card_message, name="message"),
    re_path(CHAT + r"context$", send.card_note, name="context"),
    re_path(CHAT + r"events$", events.events, name="events"),
    re_path(CHAT + r"ticket$", socket.ticket, name="ticket"),
    re_path(CHAT + r"ws$", socket.upgrade_required, name="socket"),
    re_path(CHAT + r"card$", cards.card, name="card"),
    re_path(CHAT + r"call$", cards.call, name="call"),
]
