# SPDX-License-Identifier: AGPL-3.0-or-later
from django.urls import path

from . import views

urlpatterns = [path("migrate/", views.migrate), path("budget/", views.budget)]
