# SPDX-License-Identifier: AGPL-3.0-or-later
"""Operations endpoints that run inside the Worker, because D1 cannot be reached by manage.py."""

import hmac
import io
import json
from functools import wraps

from django.conf import settings
from django.core.management import call_command
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST


def _bearer_matches(request) -> bool:
    given = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    return bool(settings.OPS_TOKEN) and hmac.compare_digest(given, settings.OPS_TOKEN)


def ops_endpoint(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not _bearer_matches(request):
            return HttpResponse(status=404)
        return view(request, *args, **kwargs)

    return csrf_exempt(require_POST(wrapped))


@ops_endpoint
def migrate(request):
    output = io.StringIO()
    call_command("migrate", interactive=False, stdout=output)
    return JsonResponse({"status": "ok", "output": output.getvalue()})


@ops_endpoint
def budget(request):
    """Model calls used today, everywhere; `{"reset": true}` zeroes every count (for tests and the owner)."""
    from chat.models import Budget
    from turns.budget import GLOBAL_SCOPE

    if request.body and json.loads(request.body).get("reset"):
        Budget.objects.all().delete()
    used = sum(Budget.objects.filter(scope=GLOBAL_SCOPE).values_list("used", flat=True))
    return JsonResponse({"used": used})
