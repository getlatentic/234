# SPDX-License-Identifier: AGPL-3.0-or-later
"""Runtime detection and configuration lookup.

Inside a Cloudflare Worker the interpreter is Pyodide (``sys.platform ==
"emscripten"``) and configuration lives on the Worker ``env`` object as vars and
secrets. Everywhere else (local development, tests, CI) configuration comes from
the process environment. Settings read through this module so they never need
to know which runtime they are running in.
"""

import os
import sys

from django.core.exceptions import ImproperlyConfigured

IS_WORKER = sys.platform == "emscripten"
IS_STATIC_BUILD = os.environ.get("WORKERS_CI") == "1"


def _read_worker_value(name: str) -> str | None:
    from workers import env

    value = getattr(env, name, None)
    return None if value is None else str(value)


def get(name: str, default: str | None = None) -> str | None:
    value = _read_worker_value(name) if IS_WORKER else os.environ.get(name)
    return default if value in (None, "") else value


def require(name: str) -> str:
    value = get(name)
    if value is None:
        raise ImproperlyConfigured(f"Missing required configuration value: {name}")
    return value


def get_bool(name: str, default: bool = False) -> bool:
    value = get(name)
    return default if value is None else value.strip().lower() in {"1", "true", "yes", "on"}


def get_int(name: str, default: int) -> int:
    value = get(name)
    return default if value is None else int(value)


def get_list(name: str, default: str = "") -> list[str]:
    raw = get(name, default) or ""
    return [item.strip() for item in raw.split(",") if item.strip()]
