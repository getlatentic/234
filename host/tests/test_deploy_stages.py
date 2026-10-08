# SPDX-License-Identifier: AGPL-3.0-or-later
"""tools/deploy.sh has two stages. Staging is a deployment of its own: every Worker, database, queue and
rate-limit namespace named apart from production's, no custom domain, and its own sign-in file. Production
deploys only a commit staging already runs. No network: `names`, and a deploy refused before it does anything
(never one that would go on: these tests run inside a deploy's own checks)."""

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
