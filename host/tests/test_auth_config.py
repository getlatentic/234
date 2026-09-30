# SPDX-License-Identifier: AGPL-3.0-or-later
"""The sign-in settings and what the public configuration says about them: no emulator, no stand-in for
Google's keys, nothing that could make the public site accept an unsigned token."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from .test_public_config import public_config, rendered

SRC = Path(__file__).resolve().parents[1] / "src"
BASE = {
    "DJANGO_SECRET_KEY": "s",
    "PATH": os.environ.get("PATH", ""),
    "DJANGO_SETTINGS_MODULE": "config.settings",
}


def load(
    extra: dict[str, str], program: str = "import config.settings as s; print('ok')"
) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", program],
        cwd=SRC,
        env={**BASE, **extra},
        capture_output=True,
        text=True,
        check=False,
    )


def test_the_public_template_sets_no_sign_in_value_and_none_for_development():
    variables = public_config()["vars"]
    assert not [
        name for name in variables if name.startswith("FIREBASE_AUTH_EMULATOR") or name == "FIREBASE_KEYS_URL"
    ]
    assert "ACCOUNT_KEY" not in variables, "the account key is a secret, not a variable"


@pytest.mark.parametrize("name", ["FIREBASE_AUTH_EMULATOR_HOST", "FIREBASE_KEYS_URL"])
def test_a_development_only_setting_stops_the_host_outside_development(name):
    value = "127.0.0.1:9099" if name.endswith("HOST") else "http://127.0.0.1:1/keys"
    refused = load({"DJANGO_DEBUG": "0", name: value})
    assert refused.returncode != 0 and "development only" in refused.stderr
    assert load({"DJANGO_DEBUG": "1", name: value}).returncode == 0
    with_owner = load({"DJANGO_DEBUG": "1", "REQUIRE_OWNER": "1", name: value})
    assert with_owner.returncode != 0 and "development only" in with_owner.stderr


def test_the_public_configuration_refuses_an_emulator_token_even_when_sign_in_is_on():
    program = (
        "import base64, json\n"
        "from accounts.firebase_token import InvalidToken\n"
        "from accounts.service import identity_of\n"
        "enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b'=').decode()\n"
        "p = 'demo-twothreefour'\n"
        "claims = {'iss': 'https://securetoken.google.com/' + p, 'aud': p, 'sub': 'u', 'email': 'a@b.c',\n"
        "          'email_verified': True, 'auth_time': 1, 'iat': 1, 'exp': 2,\n"
        "          'firebase': {'sign_in_provider': 'google.com'}}\n"
        "try:\n"
        "    identity_of(enc({'alg': 'none'}) + '.' + enc(claims) + '.', now=1)\n"
        "except InvalidToken as refused:\n"
        "    print('refused', refused)\n"
    )
    variables = rendered(HOST_WORKER="chat", SANDBOX_WORKER="chat-sandbox", SUBDOMAIN="acct")["vars"]
    public = {k: v for k, v in variables.items() if isinstance(v, str)}
    sign_in = {
        "FIREBASE_PROJECT_ID": "demo-twothreefour",
        "FIREBASE_API_KEY": "k",
        "FIREBASE_AUTH_DOMAIN": "demo.firebaseapp.com",
        "ACCOUNT_KEY": "a",
    }
    answer = load({**public, **sign_in}, program)
    assert "refused algorithm 'none' is not accepted" in answer.stdout, answer.stderr
    allowed = load(
        {**public, **sign_in, "DJANGO_DEBUG": "1", "FIREBASE_AUTH_EMULATOR_HOST": "127.0.0.1:9099"}, program
    )
    assert allowed.returncode == 0 and "refused" not in allowed.stdout, allowed.stderr


@pytest.mark.parametrize(
    ("name", "value"),
    [("FIREBASE_AUTH_DOMAIN", "a.com; script-src *"), ("FIREBASE_AUTH_EMULATOR_HOST", "a b")],
)
def test_a_value_that_goes_into_the_policy_must_be_a_host(name, value):
    assert load({"DJANGO_DEBUG": "1", name: value}).returncode != 0


def test_sign_in_needs_all_four_values_and_an_account_key_is_never_defaulted_in_production():
    three = {
        "FIREBASE_PROJECT_ID": "p-demo-1",
        "FIREBASE_API_KEY": "k",
        "FIREBASE_AUTH_DOMAIN": "p.firebaseapp.com",
    }
    program = "import config.settings as s; print(s.SIGN_IN_ENABLED)"
    assert load({"DJANGO_DEBUG": "0", **three}, program).stdout.strip() == "False"
    assert load({"DJANGO_DEBUG": "0", **three, "ACCOUNT_KEY": "a"}, program).stdout.strip() == "True"
    assert load({"DJANGO_DEBUG": "0"}, program).stdout.strip() == "False"


def test_cross_origin_opener_policy_allows_the_popup_only_where_sign_in_exists():
    program = "import config.settings as s; print(s.SECURE_CROSS_ORIGIN_OPENER_POLICY)"
    three = {
        "FIREBASE_PROJECT_ID": "p-demo-1",
        "FIREBASE_API_KEY": "k",
        "FIREBASE_AUTH_DOMAIN": "p.firebaseapp.com",
    }
    assert load({"DJANGO_DEBUG": "0"}, program).stdout.strip() == "same-origin"
    assert (
        load({"DJANGO_DEBUG": "0", **three, "ACCOUNT_KEY": "a"}, program).stdout.strip()
        == "same-origin-allow-popups"
    )


def test_the_template_marks_one_place_for_the_firebase_variables_inside_vars_and_deploy_fills_it():
    text = (Path(__file__).resolve().parents[1] / "wrangler.public.jsonc").read_text()
    lines = text.splitlines()
    marker = [i for i, line in enumerate(lines) if line.strip() == "// @FIREBASE_VARS@"]
    assert len(marker) == 1
    opened = next(i for i, line in enumerate(lines) if line.strip().startswith('"vars"'))
    assert opened < marker[0] and lines[marker[0] + 1].strip().startswith('"DJANGO_DEBUG"')
    deploy = (Path(__file__).resolve().parents[2] / "tools" / "deploy.sh").read_text()
    assert "// @FIREBASE_VARS@" in deploy and ".env.auth.local" in deploy


def test_the_env_file_of_the_values_is_ignored_by_git():
    ignore = (Path(__file__).resolve().parents[2] / ".gitignore").read_text().splitlines()
    assert ".env.auth.local" in ignore
