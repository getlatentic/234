# SPDX-License-Identifier: AGPL-3.0-or-later
from django.urls import re_path

from . import views

app_name = "pact"

urlpatterns = [
    re_path(r"^a2a/(?P<brand_id>[A-Za-z0-9_-]{1,64})/(?P<rest>.+)$", views.route, name="route"),
]
