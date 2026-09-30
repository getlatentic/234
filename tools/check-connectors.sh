#!/bin/bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# Everything that checks the four connectors: lint, the unit tests, the tests against a Worker of its own
# (concurrency on D1, the official Python and TypeScript MCP clients), the live check against the
# simulators, and the mutation check.
# usage: tools/check-connectors.sh [--no-worker]
#   CONNECTORS_PORT (default 8787) is the port of the Worker it starts; STARTUP_TEST_PORT (8881) and
#   PROBE_PORT (8889) are two more that the Worker tests use.
#   --no-worker: skip the Worker tests, when the caller already ran them on its own stack (check.sh does).
# It stops only the Worker it started, by port.
set -u
root=$(cd "$(dirname "$0")/.." && pwd)
port=${CONNECTORS_PORT:-8787}
fail=0
run() { echo "== $*"; "$@" || fail=1; }

cd "$root/checkout"
run uv run ruff check .
run uv run ruff format --check .
run uv run pytest -q

if [ "${1:-}" != "--no-worker" ]; then
  log=/tmp/cf-connectors-$port.log
  : > "$log"
  uv run pywrangler d1 migrations apply DB --local > /dev/null 2>&1
  (nohup uv run pywrangler dev --port "$port" --var ENABLE_TEST_ROUTES:1 \
    --var "PUBLIC_BASE_URL:http://localhost:$port" > "$log" 2>&1 &)
  up=0
  for _ in $(seq 1 120); do
    sleep 1
    grep -q "Ready on" "$log" && { up=1; break; }
    grep -q "ERROR" "$log" && break
  done
  if [ $up = 1 ]; then
    CHECKOUT_URL="http://localhost:$port" run uv run pytest -m worker -q
  else
    echo "the Worker did not start (see $log)"; fail=1
  fi
  lsof -ti "tcp:$port" 2>/dev/null | xargs kill 2>/dev/null || true
fi

run "$root/tools/live-check.sh" --self-test
run "$root/tools/mutation-check.sh"
[ $fail = 0 ] && echo "CONNECTOR CHECKS PASSED" || echo "CONNECTOR CHECKS FAILED"
exit $fail
