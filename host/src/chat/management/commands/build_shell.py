# SPDX-License-Identifier: AGPL-3.0-or-later
from django.core.management.base import BaseCommand

from chat.shell import write_shell


class Command(BaseCommand):
    help = "Writes the static home page (index.html) and its _headers next to the collected static files."

    def handle(self, *args, **options) -> None:
        for path in write_shell():
            self.stdout.write(path)
