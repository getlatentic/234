# SPDX-License-Identifier: AGPL-3.0-or-later
"""Undoes each guardrail once, in a throwaway copy of the project, and checks that a test fails.
The working tree is never touched.

    tools/mutation-check.sh             every guardrail
    tools/mutation-check.sh ledger      only those whose name or file contains "ledger"

Each mutation replaces one line that enforces a rule with a version that does not (a comparison that
always passes, a WHERE clause without its condition, a check removed). If the tests still pass, the rule
was never really tested, and the guardrail is reported MISSED.
"""

import os
import queue
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from tools.mutations import MUTATIONS
from tools.mutations.model import Mutation

ROOT = Path(__file__).resolve().parents[1]
HOST_ROOT = ROOT.parent / "host"
PROJECTS = {
    "checkout": (ROOT, ("src", "tests", "tools", "migrations", "pyproject.toml", "wrangler.public.jsonc")),
    "host": (HOST_ROOT, ("src", "tests", "pyproject.toml", "uv.lock", "wrangler.public.jsonc")),
}
TIMEOUT_SECONDS = 180
WORKERS = max(1, min(6, (os.cpu_count() or 2) // 2))


def copy_project(project: str) -> Path:
    source_root, copied = PROJECTS[project]
    scratch = Path(tempfile.mkdtemp(prefix=f"mutation-{project}-"))
    target = scratch / project
    target.mkdir()
    if (
        project == "host"
    ):  # the host's tests also read the vectors it shares with the sandbox, at ../sandbox/test
        shutil.copytree(
            ROOT.parent / "sandbox" / "test",
            scratch / "sandbox" / "test",
            ignore=shutil.ignore_patterns("*.mjs"),
        )
    if project == "checkout":  # its tests read the fixture sources at ../knowledge
        shutil.copytree(ROOT.parent / "knowledge", scratch / "knowledge")
    for name in copied:
        source = source_root / name
        if source.is_dir():
            shutil.copytree(source, target / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            shutil.copy(source, target / name)
    return target


def test_command(directory: Path, project: str, tests: list[str]) -> tuple[list[str], dict[str, str]]:
    """The connector's tests run in this environment; the host's in its own, over the copy."""
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "NO_COLOR": "1"}
    pytest = ["python", "-m", "pytest", "-q", "-x", "--tb=no", "-p", "no:cacheprovider", *tests]
    if project == "host":
        env["UV_PROJECT_ENVIRONMENT"] = str(HOST_ROOT / ".venv")
        return ["uv", "run", "--project", str(directory), "--frozen", "--no-sync", *pytest], env
    return [sys.executable, *pytest[1:]], {**env, "PYTHONPATH": "src"}


def run_tests(directory: Path, tests: list[str], project: str) -> subprocess.CompletedProcess[str]:
    command, env = test_command(directory, project, tests)
    return subprocess.run(
        command, cwd=directory, env=env, capture_output=True, text=True, timeout=TIMEOUT_SECONDS, check=False
    )


def first_failure(output: str) -> str:
    for line in output.splitlines():
        if line.startswith("FAILED"):
            return line.removeprefix("FAILED ").split(" - ")[0].split("::", 1)[-1]
    return "the run failed"


def apply(directory: Path, mutation: Mutation) -> str:
    path = directory / mutation.file
    original = path.read_text()
    if original.count(mutation.find) != 1:
        raise SystemExit(f'"{mutation.find}" must appear exactly once in {mutation.file}')
    path.write_text(original.replace(mutation.find, mutation.replace))
    return original


def check(directory: Path, mutation: Mutation) -> bool:
    original = apply(directory, mutation)
    try:
        result = run_tests(directory, mutation.tests, mutation.project)
    finally:
        (directory / mutation.file).write_text(original)
    if result.returncode == 0:
        print(f"MISSED  {mutation.guardrail} ({mutation.file})", flush=True)
        return False
    detail = "a test failed to load" if result.returncode not in (1,) else first_failure(result.stdout)
    print(f"caught  {mutation.guardrail} ({detail})", flush=True)
    return True


def check_project(project: str, chosen: list[Mutation]) -> int:
    """How many of these mutations no test noticed. Each worker undoes one guardrail at a time in a throwaway
    copy of its own, so the mutations run side by side without seeing each other."""
    directories = [copy_project(project) for _ in range(min(WORKERS, len(chosen)))]
    try:
        every_test = sorted({t for m in chosen for t in m.tests})
        baseline = run_tests(directories[0], every_test, project)
        if baseline.returncode != 0:
            print(f"The {project} tests fail before any guardrail is undone:")
            print(baseline.stdout + baseline.stderr)
            return -1
        free: queue.Queue[Path] = queue.Queue()
        for directory in directories:
            free.put(directory)

        def one(mutation: Mutation) -> bool:
            directory = free.get()
            try:
                return check(directory, mutation)
            finally:
                free.put(directory)

        with ThreadPoolExecutor(len(directories)) as pool:
            return list(pool.map(one, chosen)).count(False)
    finally:
        for directory in directories:
            shutil.rmtree(directory.parent, ignore_errors=True)


def main(argv: list[str]) -> int:
    wanted = argv[0].lower() if argv else ""
    chosen = [m for m in MUTATIONS if wanted in f"{m.guardrail} {m.file}".lower()]
    missed = 0
    for project in PROJECTS:
        mine = [m for m in chosen if m.project == project]
        if not mine:
            continue
        found = check_project(project, mine)
        if found < 0:
            return 2
        missed += found
    print(f"\n{len(chosen) - missed} of {len(chosen)} guardrails caught when undone.")
    return 0 if missed == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
