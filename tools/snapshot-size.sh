#!/bin/bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# Measures the startup snapshot of a Python Worker: raw and gzip-compressed bytes (Cloudflare caps the
# compressed size near 19.7 MB in practice), and how long the first
# request takes on a fresh start. The two request times are taken while workerd is saving the snapshot, which
# makes them slower than a Worker's real first requests: tools/startup-budget.sh restores the snapshot and times
# those. Touches only its own port, which is in the stack's range.
# usage: tools/snapshot-size.sh <worker dir> [port]     (default port 8990)
set -e
dir=$(cd "$1" && pwd); port=${2:-8990}
root=$(cd "$(dirname "$0")/.." && pwd)
snap=$(mktemp -d); wrapper=$(mktemp); log=$(mktemp)
real="$root/node_modules/@cloudflare/workerd-darwin-arm64/bin/workerd"
cat > "$wrapper" <<WRAP
#!/bin/bash
if [ "\$1" = "serve" ]; then
  shift
  exec "$real" serve --python-save-snapshot --python-snapshot-dir="$snap" "\$@"
fi
exec "$real" "\$@"
WRAP
chmod +x "$wrapper"
stop() { for pid in $(lsof -ti "tcp:$port" -sTCP:LISTEN 2>/dev/null) $(pgrep -f "pywrangler dev --port $port " 2>/dev/null); do kill "$pid" 2>/dev/null || true; done; }
stop; sleep 1
(cd "$dir" && MINIFLARE_WORKERD_PATH="$wrapper" exec uv run pywrangler dev --port "$port" --inspector-port $((port + 5)) \
  --persist-to "$snap/state" > "$log" 2>&1 < /dev/null) &
for _ in $(seq 1 180); do sleep 1; grep -q "Ready on" "$log" && break; grep -q ERROR "$log" && { tail -30 "$log"; stop; exit 1; }; done
first=$(curl -s -o /dev/null -w "%{time_total}" "http://localhost:$port/" || true)
warm=$(curl -s -o /dev/null -w "%{time_total}" "http://localhost:$port/" || true)
sleep 2
f=$(ls "$snap"/*.* "$snap"/* 2>/dev/null | grep -v state | head -1)
echo "snapshot file: $f"
echo "raw:  $(wc -c < "$f") bytes"
echo "gzip: $(gzip -c "$f" | wc -c) bytes"
echo "first request after a fresh start: ${first} s, next: ${warm} s"
stop
