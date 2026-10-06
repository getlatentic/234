# SPDX-License-Identifier: AGPL-3.0-or-later
from django.urls import include, path

urlpatterns = [
    path("ops/", include("ops.urls")),
    path("", include("a2a.urls")),
    path("", include("pact.urls")),
    path("", include("oauth.urls")),
    path("", include("accounts.urls")),
    path("", include("chat.urls")),
]
