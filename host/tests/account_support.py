# SPDX-License-Identifier: AGPL-3.0-or-later
"""A browser that signs in: its own cookies, the CSRF token its page carries, and the account key the tests
configure. The fixtures that turn sign-in on are in conftest.py."""

import json
import secrets

from django.test import Client

from chat.models import Chat

from .firebase_support import claims, token

ACCOUNT_KEY = "test-account-key"


class Device:
    """One browser: its own cookies and the CSRF token /api/me gives its page."""

    def __init__(self) -> None:
        self.client = Client()

    def me(self) -> dict:
        return self.client.get("/api/me").json()

    def token(self) -> str:
        return self.me()["csrf"]

    def post(self, path: str, body: dict | None = None):
        return self.client.post(
            path, json.dumps(body or {}), content_type="application/json", HTTP_X_CSRFTOKEN=self.token()
        )

    def sign_in(self, key, uid="uid-abc", email="ada@example.com", **changes):
        return self.post("/auth/session", {"idToken": token(key, claims(sub=uid, email=email, **changes))})

    def chat(self) -> str:
        owner = self.client.get("/api/me").wsgi_request.owner
        return Chat.objects.create(id=secrets.token_hex(16), owner=owner).id
