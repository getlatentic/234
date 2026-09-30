# SPDX-License-Identifier: AGPL-3.0-or-later
"""WSGI entrypoint, used by the Worker through django-cf and by local servers."""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

application = get_wsgi_application()
