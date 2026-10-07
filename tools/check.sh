#!/bin/bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# Everything, from a clean start: lint, unit tests, the startup budget of the host Worker (docs/performance.md),
# the Worker tests against local workerd and D1 (the three
# turn runners included), the browser conformance runs, the A2A runs with the official clients, the daily
# caps, the probe card, the card sandbox and the Paystack popup on a stack with a stand-in for Paystack, and the crash
# test. It uses ports 8900-8999 only.
#
# It fails fast rather than hanging: one run at a time (a lock), a refusal to start while a port in its range
# is held by something else (naming the pid), a time limit on every step, and a trap that stops what it started.
# usage: tools/check.sh           (about fifteen minutes)
set -u
root=$(cd "$(dirname "$0")/.." && pwd)
source "$root/tools/stack.sh"
fail=0
lock="$root/.stack/check.lock"
mkdir -p "$root/.stack"

if [ -e "$lock" ] && kill -0 "$(cat "$lock")" 2>/dev/null; then
  echo "Another tools/check.sh is running (pid $(cat "$lock")); one at a time."
  exit 1
fi
echo $$ > "$lock"

teardown() {
  PORT_BASE=8900 "$root/tools/down.sh" quiet
  PORT_BASE=8940 "$root/tools/down.sh" quiet
  PORT_BASE=8960 "$root/tools/down.sh" quiet
  PORT_BASE=8980 "$root/tools/down.sh" quiet
  rm -f "$lock"
}
trap teardown EXIT
trap 'exit 130' INT TERM

# limit SECONDS command...: a step that runs over its time is killed and counts as failed.
limit() {
  local seconds=$1; shift
  echo "== $* (limit ${seconds}s)"
  timeout --kill-after=10 "$seconds" "$@"
  local status=$?
  [ $status -eq 0 ] || { echo "!! failed with status $status (124 means it ran out of time)"; fail=1; }
  return $status
}
inside() { local dir=$1 seconds=$2; shift 2; (cd "$root/$dir" && limit "$seconds" "$@") || fail=1; }

limit 600 "$root/tools/check-connectors.sh" --no-worker
inside host 120 uv run ruff check src tests ../evaluation
inside host 300 uv run pytest -q
inside host 120 uv run ruff format --check src tests ../evaluation
inside host 120 uv run pytest -q -c ../evaluation/pytest.ini ../evaluation/tests
limit 300 node "$root/conformance/card-states.mjs" checks
limit 120 node --test "$root/conformance/menu-logic.test.mjs" "$root/conformance/lib.test.mjs" "$root/conformance/palette.test.mjs" "$root/conformance/tool-status.test.mjs"
limit 120 node "$root/conformance/markdown-unit.mjs"
limit 120 node --test "$root/ready/ready.test.mjs" "$root/ready/plugin.test.mjs"
limit 120 node --test "$root"/sandbox/test/*.test.mjs

for base in 8900 8940 8960 8980; do
  PORT_BASE=$base "$root/tools/down.sh" quiet
done
preflight 8900 8999 || { echo "Ports 8900-8999 are not free; stop what holds them and run again."; exit 1; }
limit 300 env PORT_BASE=8900 "$root/tools/startup-budget.sh"

echo "== stack: connectors 8900, host 8901 (Durable Object runner), model 8902, queue runner 8903, waitUntil runner 8904"
ALT_RUNNERS=1 timeout --kill-after=10 900 "$root/tools/up.sh" || { echo "!! the stack did not come up"; exit 1; }
export CHECKOUT_URL=http://localhost:8900 HOST_URL=http://localhost:8901 MODEL_URL=http://127.0.0.1:8902
inside checkout 300 uv run pytest -m worker -q
limit 300 node "$root/conformance/connectors-ts-client.mjs"
limit 300 node "$root/conformance/memory-ts-client.mjs"
for connector in paystack-pay send-money airtime food-order memory; do
  replay=()
  [ -f "$root/ready/fixtures/$connector.json" ] && replay=(--fixture "$root/ready/fixtures/$connector.json")
  limit 120 node "$root/ready/cli.mjs" "$CHECKOUT_URL/$connector/mcp" ${replay[@]+"${replay[@]}"}
done
inside host 600 env RUNNER_URLS=do=http://localhost:8901,queue=http://localhost:8903,waituntil=http://localhost:8904 \
  uv run pytest -m worker -q tests/test_worker_durable.py
inside host 300 uv run pytest -m worker -q tests/test_worker_socket.py tests/test_worker_start.py tests/test_worker_menu.py
for suite in run chat-ui chat-start chat-shell chat-home chat-starters chat-tools chat-scroll chat-states chat-composer chat-send chat-markdown chat-durable chat-cards chat-visitors chat-bridge chat-airtime sim-checkout a2a-js menu-card chat-menu chat-menu-fullscreen card-outcome-hosts; do
  limit 300 node "$root/conformance/$suite.mjs"
done
inside conformance/a2a-python 300 uv run python oracle.py
inside host 500 uv run python -u -m tests.crash_probe do --expect-finished
inside host 500 uv run python -u -m tests.crash_probe do quote --expect-finished
"$root/tools/down.sh" quiet

echo "== stack with the daily caps: global 6, per visitor 3"
CAP=6 VISITOR_CAP=3 timeout --kill-after=10 600 "$root/tools/up.sh" || { echo "!! the stack did not come up"; exit 1; }
inside host 300 uv run pytest -m worker -q tests/test_worker_limits.py
"$root/tools/down.sh" quiet

echo "== stack with a small context window (8,000 tokens, compacting at 0.75, keeping 500): compaction"
compaction_window="CONTEXT_WINDOW_TOKENS=8000 COMPACT_AT=0.75 KEEP_RECENT_TOKENS=500"
env $compaction_window timeout --kill-after=10 600 "$root/tools/up.sh" || { echo "!! the compaction stack did not come up"; exit 1; }
inside host 1200 uv run pytest -m worker -q tests/test_worker_compaction.py
limit 300 node "$root/conformance/chat-compaction.mjs"
inside host 600 env $compaction_window uv run python -u -m tests.crash_probe_compaction --expect-finished
"$root/tools/down.sh" quiet

echo "== stack with the probe card and a PACT personal agent on ports 8940-8959"
PORT_BASE=8940 PACT=1 timeout --kill-after=10 600 "$root/tools/up.sh" probe || { echo "!! the probe stack did not come up"; exit 1; }
limit 300 env -u HOST_URL -u CHECKOUT_URL -u MODEL_URL PORT_BASE=8940 node "$root/conformance/chat-probe.mjs"
limit 600 env -u HOST_URL -u CHECKOUT_URL -u MODEL_URL PORT_BASE=8940 node "$root/conformance/pact-e2e.mjs"

echo "== stack with the Paystack stand-in on ports 8960-8979: the sandbox proxy, the popup, other hosts"
PORT_BASE=8960 PAYSTACK_RIG=fake timeout --kill-after=10 600 "$root/tools/up.sh" || { echo "!! the rig stack did not come up"; exit 1; }
for suite in sandbox-proxy inline-checkout inline-checkout-hosts; do
  limit 300 env -u HOST_URL -u CHECKOUT_URL -u MODEL_URL PORT_BASE=8960 node "$root/conformance/$suite.mjs"
done
limit 300 env -u HOST_URL -u CHECKOUT_URL -u MODEL_URL PORT_BASE=8960 ENGINE=webkit node "$root/conformance/sandbox-proxy.mjs"
PORT_BASE=8960 "$root/tools/down.sh" quiet

echo "== stack with sign-in against the Firebase Auth emulator on ports 8980-8999: what 234 remembers, PACT Delegated"
PORT_BASE=8980 AUTH=1 PACT=1 VISITOR_CAP=0 timeout --kill-after=10 600 "$root/tools/up.sh" || { echo "!! the sign-in stack did not come up"; exit 1; }
limit 900 env -u HOST_URL -u CHECKOUT_URL -u MODEL_URL PORT_BASE=8980 node "$root/conformance/chat-auth.mjs"
limit 600 env -u HOST_URL -u CHECKOUT_URL -u MODEL_URL PORT_BASE=8980 node "$root/conformance/chat-memory.mjs"
limit 300 env -u HOST_URL -u CHECKOUT_URL -u MODEL_URL PORT_BASE=8980 node "$root/conformance/chat-shell.mjs"
limit 300 env -u HOST_URL -u CHECKOUT_URL -u MODEL_URL PORT_BASE=8980 node "$root/conformance/chat-sidebar.mjs"
limit 300 env -u HOST_URL -u CHECKOUT_URL -u MODEL_URL PORT_BASE=8980 node "$root/conformance/mcp-oauth.mjs"
limit 600 env -u HOST_URL -u CHECKOUT_URL -u MODEL_URL PORT_BASE=8980 node "$root/conformance/pact-delegated.mjs"
inside host 300 env AUTH=1 CHECKOUT_URL=http://localhost:8980 HOST_URL=http://localhost:8981 MODEL_URL=http://127.0.0.1:8982 \
  uv run pytest -m worker -q tests/test_worker_auth.py
PORT_BASE=8980 "$root/tools/down.sh" quiet

echo "== stack with sign-in against real key verification (no emulator) on ports 8980-8999: the token checks"
PORT_BASE=8980 AUTH=keys VISITOR_CAP=0 timeout --kill-after=10 600 "$root/tools/up.sh" || { echo "!! the keys stack did not come up"; exit 1; }
inside host 300 env AUTH=keys CHECKOUT_URL=http://localhost:8980 HOST_URL=http://localhost:8981 MODEL_URL=http://127.0.0.1:8982 \
  uv run pytest -m worker -q tests/test_worker_auth.py
PORT_BASE=8980 "$root/tools/down.sh" quiet

[ $fail = 0 ] && echo "ALL SUITES PASSED" || echo "SOME SUITES FAILED"
exit $fail
