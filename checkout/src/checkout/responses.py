# SPDX-License-Identifier: AGPL-3.0-or-later
import json
from dataclasses import dataclass, field
from typing import Any

JSON_HEADERS = {"content-type": "application/json"}
HTML_HEADERS = {"content-type": "text/html; charset=utf-8", "cache-control": "no-store"}


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: str = ""
    headers: dict[str, str] = field(default_factory=dict)


def json_response(value: Any, status: int = 200) -> HttpResponse:
    return HttpResponse(status, json.dumps(value), JSON_HEADERS)
