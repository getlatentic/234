#!/bin/bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# Undoes each guardrail once, in a scratch copy, and requires a test to fail each time.
# usage: tools/mutation-check.sh [filter]
root=$(cd "$(dirname "$0")/.." && pwd)
cd "$root/checkout" && PYTHONPATH=src exec uv run python -m tools.mutation_check "$@"
