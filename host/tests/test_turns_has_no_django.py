# SPDX-License-Identifier: AGPL-3.0-or-later
import ast
import subprocess
import sys
from pathlib import Path

TURNS = Path(__file__).resolve().parent.parent / "src" / "turns"


def _imported_modules(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


def test_no_module_of_the_turn_runner_imports_django():
    offenders = [
        str(path.relative_to(TURNS))
        for path in TURNS.rglob("*.py")
        if any(name.split(".")[0] == "django" for name in _imported_modules(path))
    ]
    assert offenders == []


def test_building_a_chat_core_loads_no_django():
    program = "import sys, turns.assembly; print(any(m.split('.')[0] == 'django' for m in sys.modules))"
    result = subprocess.run(
        [sys.executable, "-c", program], cwd=TURNS.parent, capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "False"
