# SPDX-License-Identifier: AGPL-3.0-or-later
import pytest

from .account_support import ACCOUNT_KEY
from .firebase_support import NOW, PROJECT, Google, SigningKey
from .support import ManualClock, SqliteDb


@pytest.fixture
def sql(db) -> SqliteDb:
    """Built in a sync fixture: an async test would be handed another Django connection."""
    return SqliteDb()


@pytest.fixture
def clock() -> ManualClock:
    return ManualClock()


@pytest.fixture
def chat(db):
    from chat.models import Chat

    return Chat.objects.create(owner="v:a")


@pytest.fixture
def other_chat(db):
    from chat.models import Chat

    return Chat.objects.create(owner="v:b")


@pytest.fixture(autouse=True)
def backend():
    from chat import backend as module

    from .support import FakeBackend

    fake = FakeBackend()
    module.set_backend(fake)
    yield fake
    module.set_backend(None)


@pytest.fixture
def visitor(client):
    """A browser: the test client plus the CSRF token that /api/me gives its pages."""
    import secrets

    class Browser:
        def __init__(self):
            self.client = client

        def token(self):
            return client.get("/api/me").json()["csrf"]

        def post(self, path, data=None, json=None):
            headers = {"HTTP_X_CSRFTOKEN": self.token()}
            if json is not None:
                import json as jsonlib

                return client.post(path, jsonlib.dumps(json), content_type="application/json", **headers)
            return client.post(path, data or {}, **headers)

        def new_chat(self) -> str:
            """A stored chat of this visitor, made the way the page's first message makes one."""
            from chat.models import Chat

            owner = client.get("/api/me").wsgi_request.owner
            return Chat.objects.create(id=secrets.token_hex(16), owner=owner).id

    return Browser()


@pytest.fixture(scope="module")
def key() -> SigningKey:
    return SigningKey.generate("key-1")


@pytest.fixture
def sign_in_on(settings, key, monkeypatch):
    """Sign-in with Google is on, against a stand-in for Google's keys."""
    from accounts import service

    settings.FIREBASE_PROJECT_ID = PROJECT
    settings.FIREBASE_API_KEY = "public-api-key"
    settings.FIREBASE_AUTH_DOMAIN = "demo.firebaseapp.com"
    settings.ACCOUNT_KEY = ACCOUNT_KEY
    settings.SIGN_IN_ENABLED = True
    google = Google(key)
    service.set_keys(google.cache())
    monkeypatch.setattr("accounts.service.time.time", lambda: NOW)
    yield google
    service.set_keys(None)
