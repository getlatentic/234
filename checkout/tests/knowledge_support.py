# SPDX-License-Identifier: AGPL-3.0-or-later
"""A small corpus written to a folder, loaded into a stack's database the way tools/knowledge_load.py
loads the real one. The sources are test fixtures in knowledge/fixtures: invented text, not guidance. The
local stack loads the same folder (tools/up.sh)."""

from pathlib import Path

from tools.knowledge_corpus import load_all
from tools.knowledge_load import statements

FIXTURES = Path(__file__).resolve().parents[2] / "knowledge" / "fixtures"
LICENCE = (FIXTURES / "frsc-licence-renewal.md").read_text()
DRAFT = (FIXTURES / "nimc-draft.md").read_text()
YORUBA = (FIXTURES / "jamb-yoruba.md").read_text()


def write_corpus(folder: Path, **files: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (folder / f"{name.replace('_', '-')}.md").write_text(text)
    return folder


def load_into(db, folder: Path) -> None:
    sources = load_all(folder)
    assert not [p for s in sources for p in s.problems], [s.problems for s in sources]
    db.connection.executescript("\n".join(statements(sources)))
