# SPDX-License-Identifier: AGPL-3.0-or-later
from django.apps import AppConfig


class A2AConfig(AppConfig):
    name = "a2a"

    def ready(self) -> None:
        from django.conf import settings

        from .auth import parse_tokens

        parse_tokens(settings.A2A_TOKENS)
