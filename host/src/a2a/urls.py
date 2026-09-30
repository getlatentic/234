# SPDX-License-Identifier: AGPL-3.0-or-later
from django.urls import path, re_path

from . import views

app_name = "a2a"

TASK = r"(?P<task_id>[0-9a-f]{16})"

urlpatterns = [
    path(".well-known/agent-card.json", views.agent_card, name="card"),
    path("a2a/message:send", views.message_send, name="send"),
    path("a2a/message:stream", views.message_stream, name="stream"),
    path("a2a/tasks", views.list_tasks, name="list"),
    re_path(rf"^a2a/tasks/{TASK}$", views.get_task, name="task"),
    re_path(rf"^a2a/tasks/{TASK}:subscribe$", views.subscribe, name="subscribe"),
    re_path(rf"^a2a/tasks/{TASK}:cancel$", views.cancel, name="cancel"),
]
