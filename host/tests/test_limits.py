# SPDX-License-Identifier: AGPL-3.0-or-later
"""What bounds a public deployment's cost: every Worker has a CPU limit of its own, and the host's template
names the day's caps on the model, in calls and in tokens."""

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = {"host": 30000, "checkout": 15000, "sandbox": 2000}


def template(name: str) -> dict:
    text = (ROOT / name / "wrangler.public.jsonc").read_text()
    lines = [line for line in text.splitlines() if not line.strip().startswith("//")]
    return json.loads(re.sub(r"@[A-Z_]+@", "x", "\n".join(lines)))


@pytest.mark.parametrize(("worker", "cpu_ms"), TEMPLATES.items())
def test_every_worker_has_a_cpu_limit_of_its_own(worker, cpu_ms):
    assert template(worker)["limits"] == {"cpu_ms": cpu_ms}


def test_the_hosts_template_caps_the_model_in_calls_and_in_tokens_for_everyone_and_for_each_person():
    caps = {k: int(v) for k, v in template("host")["vars"].items() if "MODEL_" in k}
    assert set(caps) == {
        "MODEL_CALLS_PER_DAY",
        "VISITOR_MODEL_CALLS_PER_DAY",
        "MODEL_TOKENS_PER_DAY",
        "VISITOR_MODEL_TOKENS_PER_DAY",
    }
    assert all(value > 0 for value in caps.values())
    assert caps["VISITOR_MODEL_TOKENS_PER_DAY"] < caps["MODEL_TOKENS_PER_DAY"]
