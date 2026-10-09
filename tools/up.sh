#!/bin/bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# Starts the local stack on workerd with local D1 and dummy secrets (no accounts, no deploy):
#   connector Worker (PORT_BASE), Django host Worker (+1), scripted fake model (+2), card sandbox Worker (+5).
# usage: [PORT_BASE=8900] [CAP=6] [VISITOR_CAP=60] [KEEP_STATE=1] [ALT_RUNNERS=1] [AUTH=1] tools/up.sh [probe]
#   AUTH=1 turns on sign-in with Google against the Firebase Auth emulator (base+7, through npx, no Java) and a
#   stand-in for Google's key document (base+17); the host is given a demo project and dummy values (docs/auth.md);
#   AUTH=keys is the same without the emulator: only tokens signed with the stand-in's key are accepted, as in public;
#   `probe` serves the probe card as the default card; CAP is the host's global daily model-call cap
#   (0 is off); VISITOR_CAP is each visitor's; KEEP_STATE=1 keeps the previous run's database;
#   ALT_RUNNERS=1 also starts a host on the queue runner and one on the waitUntil runner;
#   PAYSTACK_RIG=fake|real puts the paystack-pay connector in Paystack test mode against a stand-in on base+6: `fake`
#   answers itself, `real` forwards to Paystack's test mode with the key in the repository's .env.local,
#   which only that one process reads (see conformance/paystack-rig.mjs);
#   CONTEXT_WINDOW_TOKENS, COMPACT_AT, KEEP_RECENT_TOKENS and COMPACTION_TIMEOUT_SECONDS set when the host compacts a
#   chat's context (defaults 32000, 0.6, 6000 and 45: docs/compaction.md); small values show it on short chats;
#   PACT=1 registers a test personal agent (issuer and JWKS on base+18, served by conformance/pact-suite.mjs),
#   two Brands, 234 and food, on the PACT endpoint /a2a/<brand>/, and a signing key: with AUTH=1 as well, the
#   Brands offer PACT Delegated (docs/pact.md);
#   TURNSTILE=1 turns on the bot check before a first message with Cloudflare's published test keys (the real
#   Turnstile script and siteverify, so it needs the network; conformance/bot-check.mjs)
#   REACH=1 makes 234 an agent for people at the Skyline Brand of PACT's reference Provider, which
#   conformance/pact-reach.mjs starts on base+12 to base+14 (docs/pact.md);
#   REAL_MODEL=1 uses the model in LLM_BASE_URL, LLM_MODEL and (through host/.dev.vars.real) LLM_API_KEY
#   instead of the scripted one: see tools/real-model.sh.
set -e
source "$(dirname "$0")/stack.sh"
stop_stack
preflight "$base" $((base + 19)) || { echo "Something else holds the ports; stop it or set PORT_BASE."; exit 1; }
[ "${KEEP_STATE:-}" = "1" ] || rm -rf "$state"
mkdir -p "$state"

[ "${REAL_MODEL:-}" = "1" ] || (cd "$root/host" && uv run python tests/fake_model.py "$model_port" > "$state/model.log" 2>&1 &)
(cd "$root" && npm run build:host > /dev/null && node conformance/build-probe.mjs > /dev/null)
(cd "$root/checkout" && uv run python ../card/build.py > /dev/null && uv run python ../card/build.py src/checkout/card/card-official.html --client official > /dev/null && uv run python ../card/build.py --card menu > /dev/null && uv run python ../card/build.py --card memory > /dev/null && uv run python ../card/build.py --card brands > /dev/null)
build_shell
[ -f "$root/checkout/src/checkout/card/react-card.html" ] || cp "$root/reference/ts-demo/dist/views/card.html" "$root/checkout/src/checkout/card/react-card.html"

rig=()
if [ -n "${PAYSTACK_RIG:-}" ]; then
  (cd "$root" && PAYSTACK_RIG="$PAYSTACK_RIG" exec node conformance/paystack-rig.mjs "$rig_port" > "$state/rig.log" 2>&1 < /dev/null &)
  for _ in $(seq 1 20); do curl -s -m 1 "http://127.0.0.1:$rig_port/rig/state" > /dev/null && break; sleep 0.5; done
  # The approval card is also made to ask for origins the host's allowlist must refuse.
  rig=(--var PAYSTACK_PAY_MODE:test --var PAYSTACK_TEST_SECRET_KEY:sk_test_rigrigrig01 --var "PAYSTACK_API_URL:http://127.0.0.1:$rig_port"
    --var 'CARD_CSP_EXTRA:{"connectDomains":["https://api.evil.example.com","wss://live.evil.example.com"],"resourceDomains":["data:","*","https://*.evil.example.com"],"frameDomains":["https://checkout.paystack.com.evil.example.com"],"baseUriDomains":["https://evil.example.com"]}')
fi
card=()
[ "${1:-}" = "probe" ] && card=(--var CARD_FILE:probe-card.html)
(cd "$root/checkout" && uv run pywrangler d1 migrations apply DB --local --persist-to "$state/checkout" > /dev/null 2>&1)
(cd "$root/checkout" && PYTHONPATH=src uv run python -m tools.knowledge_load sql --dir ../knowledge/fixtures > "$state/knowledge.sql" && uv run pywrangler d1 execute DB --local --persist-to "$state/checkout" --file "$state/knowledge.sql" > /dev/null 2>&1)
start checkout "$root/checkout" "$checkout_port" "$state/checkout.log" \
  --var ENABLE_TEST_ROUTES:1 --var "PUBLIC_BASE_URL:http://localhost:$checkout_port" \
  --var "HOST_PUBLIC_URL:http://localhost:$host_port" \
  --var ALT_CARDS:react=react-card.html,probe=probe-card.html,official=card-official.html "${card[@]}" "${rig[@]}"
start_sandbox
case "${AUTH:-}" in 1 | keys) start_auth ;; esac
start_host do
if [ "${ALT_RUNNERS:-}" = "1" ]; then
  node "$root/tools/alt-config.mjs"
  start_host queue
  start_host waituntil
fi
echo "up: host http://localhost:$host_port  connectors http://localhost:$checkout_port  model http://127.0.0.1:$model_port  sandbox http://127.0.0.1:$sandbox_port"
