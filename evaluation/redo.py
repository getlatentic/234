# SPDX-License-Identifier: AGPL-3.0-or-later
"""Completing a run that lost draws to infrastructure: the draws that answered are kept as they were, and only
the others are made again. Pure, so the rule is tested without a stack."""

import argparse
import json
from pathlib import Path
from typing import Any

from .cases import Case


def lost(draw: dict[str, Any]) -> bool:
    """A draw that never got an answer from the model: setup or the host failed, or the turn did not end. A
    wrong answer is not lost, and is never drawn again."""
    return bool(draw["error"]) or draw["score"]["infra"]


def plan(cases: list[Case], args: argparse.Namespace) -> tuple[list[tuple[Case, int]], list[dict[str, Any]]]:
    """The draws to make, and the draws of an earlier run (`--redo`) that are kept as they are: all that
    answered. Only what was lost to infrastructure is made again."""
    if not args.redo:
        return [(case, n) for n in range(args.draws) for case in cases], []
    previous = [json.loads(line) for line in Path(args.redo).read_text().splitlines() if line.strip()]
    by_id = {case.id: case for case in cases}
    kept = [d for d in previous if not lost(d)]
    again = [(by_id[d["case"]], d["draw"]) for d in previous if lost(d) and d["case"] in by_id]
    return again, kept
