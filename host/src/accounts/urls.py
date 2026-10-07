# SPDX-License-Identifier: AGPL-3.0-or-later
from django.urls import path

from . import connected, views

app_name = "accounts"

urlpatterns = [
    path("auth/session", views.sign_in, name="session"),
    path("auth/signout", views.sign_out, name="signout"),
    path("connected/", connected.connections, name="connected"),
    path("connected/end", connected.end, name="connected-end"),
]
