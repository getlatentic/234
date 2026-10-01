#!/bin/bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# The startup budget of the host Worker (docs/performance.md). It saves the Worker's startup snapshot the way a
# deploy does, fails when the gzip-compressed snapshot is over BUDGET_GZIP_BYTES (a deployed snapshot is capped by
# Cloudflare near 18.5 MB compressed, and a bigger one starts a Worker slower), then restores that snapshot
# a few times and prints how long the first and the next request take on a restored Worker.
# Touches only ports PORT_BASE+18 and +19, which are in the stack's range, and its own temporary directory.
# usage: [PORT_BASE=8900] [RESTORES=3] tools/startup-budget.sh
set -u
BUDGET_GZIP_BYTES=${BUDGET_GZIP_BYTES:-12240000}
root=$(cd "$(dirname "$0")/.." && pwd)
base=${PORT_BASE:-8900}; port=$((base + 18)); restores=${RESTORES:-3}
work=$(mktemp -d); log=$work/log
real="$root/node_modules/@cloudflare/workerd-darwin-arm64/bin/workerd"
[ -x "$real" ] || real=$(ls "$root"/node_modules/@cloudflare/workerd-*/bin/workerd 2>/dev/null | head -1)
cat > "$work/workerd.sh" <<WRAP
#!/bin/bash
if [ "\$1" = "serve" ]; then shift; exec "$real" serve \$WORKERD_FLAGS "\$@"; fi
exec "$real" "\$@"
WRAP
chmod +x "$work/workerd.sh"

busy() { lsof -ti "tcp:$port" -sTCP:LISTEN 2>/dev/null; lsof -ti "tcp:$((port + 1))" -sTCP:LISTEN 2>/dev/null; }
stop() {
  local signal pid
  for signal in TERM KILL; do
    for pid in $(busy) $(pgrep -f "pywrangler dev --port $port " 2>/dev/null) $(pgrep -f "wrangler dev --port $port " 2>/dev/null); do
      kill "-$signal" "$pid" 2>/dev/null
    done
    for _ in 1 2 3 4 5 6 7 8; do [ -z "$(busy)" ] && return 0; sleep 0.5; done
  done
}
trap 'stop; rm -rf "$work"' EXIT

start() {  # workerd flags: the host Worker on its migrated database; waits until it listens
  (cd "$root/host" && WORKERD_FLAGS="$1" MINIFLARE_WORKERD_PATH="$work/workerd.sh" exec uv run pywrangler dev \
    --port "$port" --inspector-port $((port + 1)) --persist-to "$work/state" > "$log" 2>&1 < /dev/null) &
  for _ in $(seq 1 240); do
    sleep 0.5
    grep -q "Ready on" "$log" && return 0
    grep -q ERROR "$log" && { tail -30 "$log"; return 1; }
  done
  echo "the host did not start in 120 s"; return 1
}

seconds() { curl -s -o /dev/null -w '%{time_total}' "http://localhost:$port$1"; }

stop
start "--python-save-snapshot --python-snapshot-dir=$work" || exit 1
curl -s -o /dev/null -X POST "http://localhost:$port/ops/migrate/" -H 'authorization: Bearer dummy-local-ops-token'
sleep 2; stop
snapshot=$work/snapshot.bin
[ -f "$snapshot" ] || { echo "no snapshot was saved"; exit 1; }
raw=$(wc -c < "$snapshot"); gz=$(gzip -c "$snapshot" | wc -c)
echo "snapshot: raw $raw bytes, gzip $gz bytes (budget $BUDGET_GZIP_BYTES)"

firsts=(); nexts=()
for _ in $(seq 1 "$restores"); do
  start "--python-load-snapshot=snapshot.bin --python-snapshot-dir=$work" || exit 1
  firsts+=("$(seconds /api/me)"); nexts+=("$(seconds /api/me)")
  stop
done
echo "restored snapshot, GET /api/me (the home page itself is a static asset): first request ${firsts[*]} s, next request ${nexts[*]} s"

if [ "$gz" -gt "$BUDGET_GZIP_BYTES" ]; then
  echo "OVER BUDGET: the gzip snapshot is $((gz - BUDGET_GZIP_BYTES)) bytes over. docs/performance.md says what grows it."
  exit 1
fi
echo "within budget"
