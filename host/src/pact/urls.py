# SPDX-License-Identifier: AGPL-3.0-or-later
from django.urls import re_path

from . import oauth_views, views

app_name = "pact"
BRAND = r"^a2a/(?P<brand_id>[A-Za-z0-9_-]{1,64})"

OAUTH = rf"{BRAND}/oauth"

urlpatterns = [
    re_path(rf"{OAUTH}/\.well-known/oauth-authorization-server$", oauth_views.metadata, name="metadata"),
    re_path(rf"{OAUTH}/jwks\.json$", oauth_views.jwks, name="jwks"),
    re_path(rf"{OAUTH}/device_authorization$", oauth_views.device_authorization, name="device_authorization"),
    re_path(rf"{OAUTH}/token$", oauth_views.token, name="token"),
    re_path(rf"{OAUTH}/device$", oauth_views.device_page, name="device"),
    re_path(rf"{BRAND}/(?P<rest>.+)$", views.route, name="route"),
]
