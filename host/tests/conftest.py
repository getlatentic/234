# SPDX-License-Identifier: AGPL-3.0-or-later
import pytest

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
    """A browser: the test client plus the CSRF token its pages carry."""
    import re

    class Browser:
        def __init__(self):
            self.client = client

        def token(self):
            page = client.get("/")
            return re.search(r'csrf-token" content="([^"]+)', page.content.decode()).group(1)

        def post(self, path, data=None, json=None):
            headers = {"HTTP_X_CSRFTOKEN": self.token()}
            if json is not None:
                import json as jsonlib

                return client.post(path, jsonlib.dumps(json), content_type="application/json", **headers)
            return client.post(path, data or {}, **headers)

        def new_chat(self) -> str:
            """A stored chat of this visitor, made the way the page's first message makes one."""
            from chat.models import Chat

            page = client.get("/")
            chat_id = re.search(r'data-chat="([0-9a-f]{32})"', page.content.decode()).group(1)
            return Chat.objects.create(id=chat_id, owner=page.wsgi_request.owner).id

    return Browser()
