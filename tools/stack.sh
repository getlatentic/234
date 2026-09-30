# SPDX-License-Identifier: AGPL-3.0-or-later
# Shared by up.sh and down.sh: which ports the local stack uses. Nothing else on the machine is touched.
#   PORT_BASE (default 8900): connector Worker = base, host Worker = base+1, fake model = base+2,
#   and with ALT_RUNNERS=1 the hosts on the alternative turn runners: queue = base+3, waituntil = base+4;
#   the card sandbox Worker = base+5, on 127.0.0.1 while the hosts are on localhost: two hostnames, so two
#   sites, and no cookie of a host is ever sent to the sandbox; with PAYSTACK_RIG=fake|real the Paystack stand-in
#   (conformance/paystack-rig.mjs) = base+6 and the paystack-pay connector runs in Paystack test mode against it.
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
base=${PORT_BASE:-8900}
checkout_port=$base
host_port=$((base + 1))
model_port=$((base + 2))
queue_port=$((base + 3))
waituntil_port=$((base + 4))
sandbox_port=$((base + 5))
rig_port=$((base + 6))
auth_port=$((base + 7))      # with AUTH=1: the Firebase Auth emulator; its hub and logging take the next two
keys_port=$((base + 17))     # with AUTH=1: the stand-in for Google's key document
sandbox_key=dummy-local-sandbox-signing-key
state="$root/.stack/$base"

signal_tree() {  # signal pid: the process and everything it started
  local signal=$1 pid=$2 child
  for child in $(pgrep -P "$pid" 2>/dev/null); do signal_tree "$signal" "$child"; done
  kill "-$signal" "$pid" 2>/dev/null || true
}

is_ours() {  # pid: a process this repo's stack started (a launcher, a workerd, the scripted model)
  local command
  command=$(ps -o command= -p "$1" 2>/dev/null)
  case "$command" in
    *"$root/node_modules/"* | *"tests/fake_model.py"* | *"pywrangler dev --port"* | *"conformance/paystack-rig.mjs"*) return 0 ;;
    *"conformance/fake-google-keys.mjs"* | *"emulators:start --only auth --project demo-twothreefour"*) return 0 ;;
  esac
  return 1
}

stack_pids() {  # this stack's launchers (they name their port) and whatever of ours listens on its ports
  local port pid
  for port in $(seq "$base" $((base + 19))); do
    pgrep -f "wrangler dev --port $port " 2>/dev/null || true
    for pid in $(lsof -ti "tcp:$port" -sTCP:LISTEN 2>/dev/null); do is_ours "$pid" && echo "$pid"; done
  done | sort -u
}

stop_stack() {
  local pid attempt signal
  for signal in TERM KILL; do
    for pid in $(stack_pids); do signal_tree "$signal" "$pid"; done
    for attempt in 1 2 3 4 5 6 7 8; do
      [ -z "$(stack_pids)" ] && break
      sleep 0.5
    done
  done
}

preflight() {  # first last: refuses when a port in the range is bound, and says by whom
  local port pid busy=0
  for port in $(seq "$1" "$2"); do
    for pid in $(lsof -ti "tcp:$port" -sTCP:LISTEN 2>/dev/null); do
      echo "port $port is already in use by pid $pid: $(ps -o command= -p "$pid" | cut -c1-110)" >&2
      busy=1
    done
  done
  return $busy
}

start() {  # name dir port log args...: one Worker on workerd, local D1, its own state directory
  local name=$1 dir=$2 port=$3 log=$4; shift 4
  : > "$log"
  (cd "$dir" && exec uv run pywrangler dev --port "$port" --inspector-port $((port + 10)) --persist-to "$state/$name" "$@") > "$log" 2>&1 < /dev/null &
  for _ in $(seq 1 180); do
    sleep 1
    grep -q "Ready on" "$log" && return 0
    grep -q "ERROR" "$log" && { echo "FAILED to start $name (see $log)"; grep -m3 "ERROR" "$log" | cut -c1-160; return 1; }
  done
  echo "TIMEOUT starting $name (see $log)"; return 1
}

start_sandbox() {  # the card sandbox: a static JavaScript Worker that answers only for the hosts of this stack
  local origins="http://localhost:$host_port,http://localhost:$queue_port,http://localhost:$waituntil_port"
  local log="$state/sandbox.log"
  : > "$log"
  (cd "$root/sandbox" && WRANGLER_SEND_METRICS=false exec "$root/node_modules/.bin/wrangler" dev --port "$sandbox_port" \
    --inspector-port $((sandbox_port + 10)) --ip 127.0.0.1 --var "HOST_ORIGINS:$origins" --var "SIGNING_KEY:$sandbox_key") > "$log" 2>&1 < /dev/null &
  for _ in $(seq 1 60); do
    sleep 1
    curl -s -m 2 "http://127.0.0.1:$sandbox_port/health" > /dev/null && return 0
    grep -q "ERROR" "$log" && { echo "FAILED to start the sandbox (see $log)"; return 1; }
  done
  echo "TIMEOUT starting the sandbox (see $log)"; return 1
}

host_vars() {  # port: what every host gets, the runner variants included
  local model="--var LLM_BASE_URL:http://127.0.0.1:$model_port/v1"
  [ "${REAL_MODEL:-}" = "1" ] && model="--env real --var LLM_BASE_URL:$LLM_BASE_URL --var LLM_MODEL:$LLM_MODEL"
  local auth=""
  case "${AUTH:-}" in
    1 | keys) auth="--var FIREBASE_PROJECT_ID:demo-twothreefour --var FIREBASE_API_KEY:fake-api-key-for-the-emulator --var FIREBASE_AUTH_DOMAIN:localhost --var ACCOUNT_KEY:dummy-local-account-key --var FIREBASE_KEYS_URL:http://127.0.0.1:$keys_port/keys" ;;
  esac
  [ "${AUTH:-}" = "1" ] && auth="$auth --var FIREBASE_AUTH_EMULATOR_HOST:127.0.0.1:$auth_port"
  echo --var "CHECKOUT_MCP_URL:http://localhost:$checkout_port" $model $auth \
    --var "PUBLIC_BASE_URL:http://localhost:$1" --var "MODEL_CALLS_PER_DAY:${CAP:-0}" \
    --var "VISITOR_MODEL_CALLS_PER_DAY:${VISITOR_CAP:-60}" --var "WATCHDOG_SECONDS:${WATCHDOG_SECONDS:-30}" \
    --var "SANDBOX_ORIGIN:http://127.0.0.1:$sandbox_port" --var "SANDBOX_SIGNING_KEY:$sandbox_key" --var "INLINE_PAYSTACK:${INLINE_PAYSTACK:-1}" \
    --var "CONTEXT_WINDOW_TOKENS:${CONTEXT_WINDOW_TOKENS:-32000}" --var "COMPACT_AT:${COMPACT_AT:-0.6}" \
    --var "KEEP_RECENT_TOKENS:${KEEP_RECENT_TOKENS:-6000}" --var "COMPACTION_TIMEOUT_SECONDS:${COMPACTION_TIMEOUT_SECONDS:-45}"
}

start_host() {  # do|queue|waituntil: the host on that turn runner; a start that collides with a leftover is tried again
  local attempt
  for attempt in 1 2 3; do
    start_host_once "$1" && return 0
    echo "the $1 host did not come up (attempt $attempt)" >&2
    stop_host "$1"
  done
  return 1
}

start_host_once() {
  case "$1" in
    do) start host "$root/host" "$host_port" "$state/host.log" $(host_vars "$host_port") || return 1 ;;
    queue | waituntil)
      local port=$queue_port
      [ "$1" = waituntil ] && port=$waituntil_port
      start "host-$1" "$root/host" "$port" "$state/host-$1.log" --config wrangler.alt.jsonc --var "TURN_RUNNER:$1" \
        $(host_vars "$port") || return 1 ;;
  esac
  curl -s -m 20 -X POST "localhost:$(host_port_of "$1")/ops/migrate/" -H 'authorization: Bearer dummy-local-ops-token' > /dev/null
}

host_port_of() {
  case "$1" in do) echo "$host_port" ;; queue) echo "$queue_port" ;; waituntil) echo "$waituntil_port" ;; esac
}

stop_host() {  # do|queue|waituntil: SIGKILL, as a crash would, and wait until its ports are free
  local port pid attempt
  port=$(host_port_of "$1")
  for pid in $(pgrep -f "wrangler dev --port $port " 2>/dev/null) $(lsof -ti "tcp:$port" -sTCP:LISTEN 2>/dev/null) \
      $(lsof -ti "tcp:$((port + 10))" -sTCP:LISTEN 2>/dev/null); do
    signal_tree KILL "$pid"
  done
  for attempt in $(seq 1 20); do
    [ -z "$(lsof -ti "tcp:$port" -sTCP:LISTEN 2>/dev/null)$(lsof -ti "tcp:$((port + 10))" -sTCP:LISTEN 2>/dev/null)" ] && return 0
    sleep 0.5
  done
}

FIREBASE_TOOLS=15.32.0

start_auth() {  # the stand-in for Google's keys and, with AUTH=1, the Firebase Auth emulator (no Java, no login, a demo project)
  local dir="$state/firebase" log="$state/firebase.log"
  mkdir -p "$dir"
  cat > "$dir/firebase.json" <<JSON
{"emulators": {"auth": {"host": "127.0.0.1", "port": $auth_port}, "hub": {"host": "127.0.0.1", "port": $((base + 8))},
  "logging": {"host": "127.0.0.1", "port": $((base + 9))}, "ui": {"enabled": false}, "singleProjectMode": true}}
JSON
  : > "$log"
  [ "${AUTH:-}" = "1" ] && (cd "$dir" && exec npx --yes "firebase-tools@$FIREBASE_TOOLS" emulators:start --only auth --project demo-twothreefour > "$log" 2>&1 < /dev/null &)
  (cd "$root" && exec node conformance/fake-google-keys.mjs "$keys_port" "$state/keys" > "$state/keys.log" 2>&1 < /dev/null &)
  for _ in $(seq 1 90); do
    sleep 1
    { [ "${AUTH:-}" != "1" ] || curl -s -m 1 "http://127.0.0.1:$auth_port/" > /dev/null; } && curl -s -m 1 "http://127.0.0.1:$keys_port/served" > /dev/null && return 0
  done
  echo "TIMEOUT starting the Firebase emulator (see $log)"; return 1
}
