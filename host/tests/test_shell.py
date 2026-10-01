# SPDX-License-Identifier: AGPL-3.0-or-later
import re

import pytest
from django.core.management import call_command
from django.test import Client

from chat.security import page_headers, page_policy
from chat.shell import CACHE_CONTROL, PLACEHOLDER_CHAT, headers_file, render_shell

pytestmark = pytest.mark.django_db


def rules(text: str) -> dict[str, str]:
    path, *lines = text.strip().splitlines()
    assert path == "/"
    return dict(line.strip().split(": ", 1) for line in lines)


def test_the_shell_is_the_same_for_everyone_and_holds_nothing_of_a_visitor():
    html = render_shell()
    assert html == render_shell() == Client().get("/").content.decode()
    assert "csrf-token" not in html and not re.search(r'name="csrfmiddlewaretoken" value="[^"]', html)
    assert html.count(PLACEHOLDER_CHAT) > 5 and "data-shell" in html and 'data-me-url="/api/me"' in html
    assert "<chat-account" not in html


def test_where_sign_in_is_on_the_shell_holds_the_account_in_templates_and_no_firebase_value(sign_in_on):
    html = render_shell()
    account = html.split("<chat-account", 1)[1].split("</chat-account>", 1)[0]
    assert account.count("<template") == 2 and 'data-kind="signed-in"' in account
    for value in ("public-api-key", "demo.firebaseapp.com", "ada@example.com"):
        assert value not in html


def test_the_headers_file_carries_the_pages_policy_and_its_caching():
    served = rules(headers_file())
    assert served["Content-Security-Policy"] == page_policy()
    assert served["Cache-Control"] == CACHE_CONTROL
    assert served["X-Frame-Options"] == "DENY" and served["X-Content-Type-Options"] == "nosniff"
    assert served["Referrer-Policy"] == "same-origin"
    assert served["Cross-Origin-Opener-Policy"] == "same-origin"


def assert_headers_match(answer) -> None:
    for name, value in page_headers().items():
        assert answer[name] == value


def test_the_shell_is_served_under_the_headers_django_gives_its_pages(settings):
    settings.SANDBOX_ORIGIN = "https://sandbox.example.com"
    assert_headers_match(Client().get("/"))
    assert "apis.google.com" not in headers_file()


def test_with_sign_in_the_shell_and_the_pages_get_the_same_narrow_additions(sign_in_on, settings):
    settings.SANDBOX_ORIGIN = "https://sandbox.example.com"
    settings.SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin-allow-popups"
    assert_headers_match(Client().get("/"))
    policy = rules(headers_file())["Content-Security-Policy"]
    assert "script-src 'self' https://apis.google.com;" in policy
    assert "frame-src https://sandbox.example.com https://demo.firebaseapp.com;" in policy


def test_a_line_of_the_headers_file_stays_under_the_limit_of_workers_static_assets(sign_in_on, settings):
    settings.FIREBASE_AUTH_EMULATOR_HOST = "127.0.0.1:9099"
    assert max(map(len, headers_file().splitlines())) < 2000


def test_the_build_writes_the_page_and_its_headers_beside_the_static_files(settings, tmp_path):
    settings.STATIC_ROOT = tmp_path / "staticfiles" / "static"
    call_command("build_shell")
    assert (tmp_path / "staticfiles" / "index.html").read_text() == render_shell()
    assert (tmp_path / "staticfiles" / "_headers").read_text() == headers_file()
    assert not (tmp_path / "staticfiles" / "static").exists()
