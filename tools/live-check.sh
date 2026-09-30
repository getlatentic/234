#!/bin/bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# Checks the real Paystack test API and the VTpass sandbox with keys you provide in the environment (or
# --env-file). Prints nothing secret; refuses a live key; with no keys it checks nothing and exits 3.
# usage: tools/live-check.sh [--self-test] [--no-transfer] [--pay] [--env-file FILE]
root=$(cd "$(dirname "$0")/.." && pwd)
cd "$root/checkout" && PYTHONPATH=src exec uv run python -m tools.live_check "$@"
