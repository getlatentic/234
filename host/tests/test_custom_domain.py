# SPDX-License-Identifier: AGPL-3.0-or-later
"""The public deployment on a custom domain: what tools/deploy.sh makes of the wrangler templates with and
without CUSTOM_DOMAIN. The rendering is the script's own (`deploy.sh render`): stub names, no network."""

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "tools" / "deploy.sh"
HOST_TEMPLATE = ROOT / "host" / "wrangler.public.jsonc"
SANDBOX_TEMPLATE = ROOT / "sandbox" / "wrangler.public.jsonc"
CONNECTORS_TEMPLATE = ROOT / "checkout" / "wrangler.public.jsonc"
EXAMPLE = "234.example.com"
STUBS = {
    "SUBDOMAIN": "acct",
    "HOST_WORKER": "chat",
    "CONNECTORS_WORKER": "chat-connectors",
    "SANDBOX_WORKER": "chat-sandbox",
    "HOST_DB_ID": "00000000-0000-0000-0000-00000000000a",
    "LEDGER_DB_ID": "00000000-0000-0000-0000-00000000000b",
}


OTHER_NAMES = {
    "HOST_DB": "db",
    "LEDGER_DB": "led",
    "RATE_LIMIT_NAMESPACE": "1",
    "MCP_RATE_LIMIT_NAMESPACE": "2",
    "METRICS_DATASET": "chat_metrics",
}


def run_render(template: Path, out: Path, **env: str) -> subprocess.CompletedProcess:
    isolated = {
        "PATH": os.environ["PATH"],
        "DEPLOY_ENV_FILE": "/dev/null",
        "AUTH_FILE": "/nonexistent",
        **STUBS,
        **env,
    }
    return subprocess.run(
        ["bash", str(DEPLOY), "render", str(template), str(out)], env=isolated, capture_output=True, text=True
    )


def rendered(template: Path, tmp_path: Path, **env: str) -> dict:
    out = tmp_path / "rendered.jsonc"
    done = run_render(template, out, **env)
    assert done.returncode == 0, done.stderr
    lines = [line for line in out.read_text().splitlines() if not line.strip().startswith("//")]
    return json.loads("\n".join(lines))


def filled_by_hand(template: Path) -> dict:
    """The template with only its @NAMES@ filled in: what a deployment without a custom domain always was."""
    lines = [line for line in template.read_text().splitlines() if not line.strip().startswith("//")]
    names = {**STUBS, **OTHER_NAMES}
    return json.loads(re.sub(r"@([A-Z_]+)@", lambda found: names[found.group(1)], "\n".join(lines)))


@pytest.mark.parametrize("template", [HOST_TEMPLATE, SANDBOX_TEMPLATE, CONNECTORS_TEMPLATE])
def test_without_a_custom_domain_the_rendered_templates_are_what_they_always_were(template, tmp_path):
    config = rendered(template, tmp_path, **OTHER_NAMES)
    assert config == filled_by_hand(template)
    assert "routes" not in config


def test_without_a_custom_domain_every_origin_is_the_workers_dev_address(tmp_path):
    host = rendered(HOST_TEMPLATE, tmp_path)["vars"]
    assert host["DJANGO_ALLOWED_HOSTS"] == "chat.acct.workers.dev"
    assert host["DJANGO_CSRF_TRUSTED_ORIGINS"] == host["PUBLIC_BASE_URL"] == "https://chat.acct.workers.dev"
    assert rendered(SANDBOX_TEMPLATE, tmp_path)["vars"]["HOST_ORIGINS"] == "https://chat.acct.workers.dev"
    assert (
        rendered(CONNECTORS_TEMPLATE, tmp_path)["vars"]["HOST_PUBLIC_URL"] == "https://chat.acct.workers.dev"
    )


def test_with_a_custom_domain_the_host_gets_a_custom_domain_route(tmp_path):
    config = rendered(HOST_TEMPLATE, tmp_path, CUSTOM_DOMAIN=EXAMPLE)
    assert config["routes"] == [{"pattern": EXAMPLE, "custom_domain": True}]
    assert config["workers_dev"] is True and config["name"] == "chat"
    assert "routes" not in rendered(SANDBOX_TEMPLATE, tmp_path, CUSTOM_DOMAIN=EXAMPLE)
    assert "routes" not in rendered(CONNECTORS_TEMPLATE, tmp_path, CUSTOM_DOMAIN=EXAMPLE)


def test_with_a_custom_domain_it_is_the_canonical_origin_and_workers_dev_is_still_accepted(tmp_path):
    host = rendered(HOST_TEMPLATE, tmp_path, CUSTOM_DOMAIN=EXAMPLE)["vars"]
    assert host["PUBLIC_BASE_URL"] == f"https://{EXAMPLE}"
    assert host["DJANGO_ALLOWED_HOSTS"].split(",") == ["chat.acct.workers.dev", EXAMPLE]
    assert host["DJANGO_CSRF_TRUSTED_ORIGINS"].split(",") == [
        "https://chat.acct.workers.dev",
        f"https://{EXAMPLE}",
    ]
    assert (
        rendered(CONNECTORS_TEMPLATE, tmp_path, CUSTOM_DOMAIN=EXAMPLE)["vars"]["HOST_PUBLIC_URL"]
        == f"https://{EXAMPLE}"
    )


def test_the_sandbox_stays_on_workers_dev_and_frames_both_origins_of_the_host(tmp_path):
    host = rendered(HOST_TEMPLATE, tmp_path, CUSTOM_DOMAIN=EXAMPLE)["vars"]
    sandbox = rendered(SANDBOX_TEMPLATE, tmp_path, CUSTOM_DOMAIN=EXAMPLE)["vars"]
    assert host["SANDBOX_ORIGIN"] == "https://chat-sandbox.acct.workers.dev"
    assert host["SANDBOX_ORIGIN"] not in host["DJANGO_CSRF_TRUSTED_ORIGINS"]
    assert sandbox["HOST_ORIGINS"].split(",") == ["https://chat.acct.workers.dev", f"https://{EXAMPLE}"]
    assert host["SANDBOX_ORIGIN"] != host["PUBLIC_BASE_URL"]


@pytest.mark.parametrize(
    "bad",
    [
        f"https://{EXAMPLE}",
        f"{EXAMPLE}/",
        "chat.acct.workers.dev",
        "Example.COM",
        "localhost",
        "a b.example.com",
    ],
)
def test_a_custom_domain_that_is_not_a_host_name_of_a_zone_is_refused(bad, tmp_path):
    done = run_render(HOST_TEMPLATE, tmp_path / "out.jsonc", CUSTOM_DOMAIN=bad)
    assert done.returncode != 0 and "CUSTOM_DOMAIN" in done.stderr
    assert not (tmp_path / "out.jsonc").exists()


def test_the_rendered_origins_are_what_django_reads_them_as(tmp_path):
    host = rendered(HOST_TEMPLATE, tmp_path, CUSTOM_DOMAIN=EXAMPLE)["vars"]
    from config import runtime

    for name in ("DJANGO_ALLOWED_HOSTS", "DJANGO_CSRF_TRUSTED_ORIGINS"):
        os.environ[name] = host[name]
    try:
        assert runtime.get_list("DJANGO_ALLOWED_HOSTS") == ["chat.acct.workers.dev", EXAMPLE]
        assert runtime.get_list("DJANGO_CSRF_TRUSTED_ORIGINS") == [
            "https://chat.acct.workers.dev",
            f"https://{EXAMPLE}",
        ]
    finally:
        os.environ.pop("DJANGO_ALLOWED_HOSTS")
        os.environ.pop("DJANGO_CSRF_TRUSTED_ORIGINS")
