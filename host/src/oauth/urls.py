# SPDX-License-Identifier: AGPL-3.0-or-later
from django.urls import path, re_path

from . import gateway, views

app_name = "oauth"

CONNECTOR = r"(?P<connector>[a-z][a-z0-9-]{0,40})"

urlpatterns = [
    path(".well-known/oauth-authorization-server", views.authorization_server, name="metadata"),
    re_path(
        rf"^\.well-known/oauth-protected-resource/mcp/{CONNECTOR}$", views.protected_resource, name="resource"
    ),
    path("oauth/authorize", views.authorize, name="authorize"),
    path("oauth/token", views.token, name="token"),
    path("oauth/register", views.register, name="register"),
    path("oauth/revoke", views.revoke, name="revoke"),
    re_path(rf"^mcp/{CONNECTOR}$", gateway.mcp, name="mcp"),
]
