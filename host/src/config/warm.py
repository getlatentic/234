# SPDX-License-Identifier: AGPL-3.0-or-later
"""Work Django does on a process's first request, done at import: the Worker's startup snapshot then holds the
URL tables, the view modules and every compiled template, so the first request after a cold start has less
left to do."""

from pathlib import Path

from django.template import engines
from django.template.utils import get_app_template_dirs
from django.templatetags.static import static
from django.urls import resolve, reverse


def _compile_templates() -> None:
    backend = engines["django"]
    for directory in map(Path, [*backend.engine.dirs, *get_app_template_dirs("templates")]):
        for path in directory.rglob("*.html"):
            backend.get_template(path.relative_to(directory).as_posix())


def warm_up() -> None:
    reverse("chat:index")
    resolve("/")
    static("chat/app.css")
    _compile_templates()
