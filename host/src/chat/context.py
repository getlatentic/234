# SPDX-License-Identifier: AGPL-3.0-or-later
import json

from django.conf import settings
from django.http import HttpRequest

from . import sandbox
from .palette import GROUND


def tagline(name: str) -> str:
    return f"Talk and do anything with {name}."


def product(request: HttpRequest) -> dict[str, object]:
    return {
        "product_name": settings.PRODUCT_NAME,
        "product_tagline": tagline(settings.PRODUCT_NAME),
        "ground": GROUND,
        "sandbox_origin": settings.SANDBOX_ORIGIN,
        "sandbox_capabilities": json.dumps(sandbox.host_sandbox()),
    }
