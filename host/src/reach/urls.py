# SPDX-License-Identifier: AGPL-3.0-or-later
from django.urls import path

from . import views

app_name = "reach"

urlpatterns = [path(".well-known/jwks.json", views.jwks, name="jwks")]
