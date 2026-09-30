# SPDX-License-Identifier: AGPL-3.0-or-later
"""No key-shaped text sits in the repository: test keys in tests are put together at run time."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEY_SHAPED = re.compile(r"\b(?:sk|pk)_(?:test|live)_[A-Za-z0-9]{8,}")
THE_SIMULATORS_OWN_KEY = "sk_test_simulated"


def test_no_source_file_holds_a_key_shaped_string():
    offenders = []
    for folder in ("src", "tests", "tools", "migrations"):
        for path in (ROOT / folder).rglob("*"):
            if path.suffix in {".py", ".sql", ".html", ".md"} and "__pycache__" not in path.parts:
                for match in KEY_SHAPED.findall(path.read_text()):
                    if match != THE_SIMULATORS_OWN_KEY:
                        offenders.append(f"{path.relative_to(ROOT)}: {match[:12]}...")
    for name in ("wrangler.jsonc", "pyproject.toml"):
        offenders += [f"{name}: {m[:12]}..." for m in KEY_SHAPED.findall((ROOT / name).read_text())]
    assert offenders == []
