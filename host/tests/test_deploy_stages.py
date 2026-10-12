# SPDX-License-Identifier: AGPL-3.0-or-later
"""tools/deploy.sh has two stages. Staging is a deployment of its own: every Worker, database, queue and
rate-limit namespace named apart from production's, no custom domain, and its own sign-in file. Production
deploys only a commit staging already runs. No network: `names`, and a deploy refused before it does anything
(never one that would go on: these tests run inside a deploy's own checks)."""

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "tools" / "deploy.sh"


def run(*args: str, **env: str) -> subprocess.CompletedProcess:
    isolated = {"PATH": os.environ["PATH"], "DEPLOY_ENV_FILE": "/dev/null", "SUBDOMAIN": "acct", **env}
    return subprocess.run(
        ["bash", str(DEPLOY), *args], env=isolated, capture_output=True, text=True, cwd=ROOT
    )


def names(**env: str) -> dict[str, str]:
    done = run("names", **env)
    assert done.returncode == 0, done.stderr
    return {line[:19].strip(): line[19:].strip() for line in done.stdout.splitlines()}


def test_staging_names_everything_apart_from_production():
    production, staging = names(), names(STAGE="staging")
    assert production["stage"] == "production" and staging["stage"] == "staging"
    for part in ("sandbox Worker", "host Worker", "connectors Worker", "host database", "ledger database",
                 "rate limit"):  # fmt: skip
        assert production[part] != staging[part], part
    assert staging["host Worker"].startswith("ask234-staging ")
    assert (
        staging["host database"] == "ask234-staging-host-db"
        and staging["ledger database"] == "ask234-staging-ledger"
    )


def test_staging_has_no_custom_domain_even_when_production_does():
    assert names(CUSTOM_DOMAIN="234.example.com")["custom domain"].startswith("https://234.example.com")
    assert names(STAGE="staging", CUSTOM_DOMAIN="234.example.com")["custom domain"].startswith("none")


def test_an_unknown_stage_is_refused():
    assert run("names", STAGE="prod").returncode != 0


def test_production_refuses_a_commit_staging_has_not_run(tmp_path):
    staged = tmp_path / "staged-commit"
    staged.write_text("0" * 40 + "\n")
    done = run("deploy", STAGED_FILE=str(staged))
    assert done.returncode != 0 and "to staging first: STAGE=staging tools/deploy.sh" in done.stderr


def test_deploy_fills_the_site_key_into_the_host_template_and_the_keys_file_is_ignored_by_git():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    template = (root / "host" / "wrangler.public.jsonc").read_text().splitlines()
    marker = [i for i, line in enumerate(template) if line.strip() == "// @TURNSTILE_VARS@"]
    opened = next(i for i, line in enumerate(template) if line.strip().startswith('"vars"'))
    assert len(marker) == 1 and opened < marker[0]
    deploy = (root / "tools" / "deploy.sh").read_text()
    assert "// @TURNSTILE_VARS@" in deploy and ".env.turnstile.local" in deploy
    assert ".env.turnstile.local" in (root / ".gitignore").read_text().replace(
        ".env.*", ".env.turnstile.local"
    )


def fake_wrangler(tmp_path: Path, stdout: str, stderr: str, status: int) -> str:
    """A wrangler that answers every call the same way and records that it was called."""
    script = tmp_path / "wrangler"
    lines = [
        "#!/bin/bash",
        f"echo \"$@\" >> '{tmp_path}/calls'",
        f"printf '%s' '{stdout}'",
        f"printf '%s' '{stderr}' >&2",
        f"exit {status}",
    ]
    script.write_text("\n".join(lines) + "\n")
    script.chmod(0o755)
    return str(script)


def test_the_secrets_of_a_worker_are_listed_by_name(tmp_path):
    kept = ("APPROVAL_SECRET", "MCP_ACCESS_TOKEN")
    listed = json.dumps([{"name": name, "type": "secret_text"} for name in kept])
    done = run("secrets", "connectors", WRANGLER=fake_wrangler(tmp_path, listed, "", 0))
    assert done.returncode == 0 and done.stdout.split() == ["APPROVAL_SECRET", "MCP_ACCESS_TOKEN"]


def test_a_worker_that_does_not_exist_yet_has_no_secrets(tmp_path):
    missing = 'X Worker "ask234-connectors" not found.'
    done = run("secrets", "connectors", WRANGLER=fake_wrangler(tmp_path, "", missing, 1))
    assert done.returncode == 0 and done.stdout.strip() == ""


def test_secrets_that_cannot_be_read_are_not_read_as_none(tmp_path):
    """Cloudflare's API answering 504 once made a deploy think no Worker had a secret, make a new token for
    the connectors, and fail before giving it to the host."""
    down = "A request to the Cloudflare API failed: 504 Gateway Timeout"
    done = run("secrets", "host", WRANGLER=fake_wrangler(tmp_path, "", down, 1))
    assert done.returncode != 0 and "cannot read those secrets" in done.stderr
