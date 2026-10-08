#!/bin/bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# The public deployment on Cloudflare: three Workers (the card sandbox, the chat host and the connectors), two D1
# databases. Every name lives in the block below and nowhere else; the wrangler configs are templates
# (sandbox/, host/ and checkout/wrangler.public.jsonc) filled in from it. docs/deploy.md is the runbook.
#
#   tools/deploy.sh                       checks, then deploys the three Workers (the sandbox first) and smoke-tests them (curl only)
#   tools/deploy.sh init                  creates the two D1 databases when they do not exist
#   tools/deploy.sh secret host NAME      sets one of the owner's secrets from stdin (the value is never printed)
#   tools/deploy.sh rotate NAME           a new value for a secret made here: token (host to connectors, set on both),
#                                         EVENTS_SECRET (the host's events key), PACT_SIGNING_KEY (the host's
#                                         PACT Delegated key: tokens and receipts it signed stop verifying),
#                                         PACT_AGENT_KEY (234's key as an agent at other Brands: re-register it),
#                                         SANDBOX_SIGNING_KEY (host and sandbox, set on both), DJANGO_SECRET_KEY
#                                         or APPROVAL_SECRET
#   tools/deploy.sh upload host|connectors|sandbox  uploads the committed code again with no checks (a secret the host bakes in
#                                         at startup takes effect only in a new version: `rotate` does this itself)
#   tools/deploy.sh versions|rollback|tail host|connectors|sandbox
#   tools/deploy.sh auth                  what .env.auth.local holds for sign-in with Google (names only) and what a deploy does with it
#   tools/deploy.sh names                 what this deploys and where it answers
#   tools/deploy.sh destroy               deletes the three Workers and both databases, after you type the host's name
#
# A deploy refuses when the working tree has uncommitted changes, so what is live is a commit.
# Nothing here reads or prints a secret: signing secrets are generated with openssl and go to wrangler on stdin.
# Sign-in with Google is configured by the untracked file .env.auth.local (docs/auth.md): three public Firebase
# identifiers, set as Worker variables; a value is never printed. Without the file the site has no sign-in.
# Any name below can be overridden from the environment (HOST_WORKER=old tools/deploy.sh destroy) or from the
# untracked file .env.deploy.local at the repository root (plain NAME=value lines, read by the shell).
# SUBDOMAIN, your account's workers.dev subdomain, has no default and must be set.
# CUSTOM_DOMAIN (optional, the same two places, for example 234.example.com) puts the host on a domain of a zone
# in your Cloudflare account: a route with custom_domain, the canonical origin settings, the sandbox's allowed
# embedder, and smoke checks of that origin. The host also keeps answering on its workers.dev address.
#   tools/deploy.sh render TEMPLATE OUT   fills in a wrangler template without deploying (the tests use it)
#
# STAGE=staging (any command) works on a second deployment of its own: the same names with -staging, its own
# databases, queues and rate-limit namespaces, no custom domain, and sign-in only from .env.auth.staging.local.
# A production deploy refuses a commit that has not first deployed to staging and passed its smoke test there
# (the commit is recorded in .stack/staged-commit); SKIP_STAGING=1 deploys anyway and says so.
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
env_file=${DEPLOY_ENV_FILE:-$root/.env.deploy.local}
# shellcheck disable=SC1090
[ ! -f "$env_file" ] || source "$env_file"

STAGE=${STAGE:-production}
case "$STAGE" in
  production) stage="" namespaces=(4391 4392) ;;
  staging) stage="-staging" namespaces=(4393 4394) CUSTOM_DOMAIN="" AUTH_FILE=${AUTH_FILE:-$root/.env.auth.staging.local} ;;
  *) echo "deploy: STAGE is production or staging" >&2; exit 1 ;;
esac
HOST_WORKER=${HOST_WORKER:-ask234$stage}
CONNECTORS_WORKER=${CONNECTORS_WORKER:-ask234-connectors$stage}
SANDBOX_WORKER=${SANDBOX_WORKER:-ask234-sandbox$stage}
HOST_DB=${HOST_DB:-ask234$stage-host-db}
LEDGER_DB=${LEDGER_DB:-ask234$stage-ledger}
SUBDOMAIN=${SUBDOMAIN:-}
CUSTOM_DOMAIN=${CUSTOM_DOMAIN:-}
[ -n "$SUBDOMAIN" ] || { echo "deploy: set SUBDOMAIN to your account's workers.dev subdomain (environment or .env.deploy.local; docs/deploy.md)" >&2; exit 1; }
RATE_LIMIT_NAMESPACE=${RATE_LIMIT_NAMESPACE:-${namespaces[0]}}
MCP_RATE_LIMIT_NAMESPACE=${MCP_RATE_LIMIT_NAMESPACE:-${namespaces[1]}}
STAGED_FILE=${STAGED_FILE:-$root/.stack/staged-commit}
METRICS_DATASET=${METRICS_DATASET:-${HOST_WORKER//-/_}_metrics}
if [ -n "$CUSTOM_DOMAIN" ]; then
  [[ $CUSTOM_DOMAIN =~ ^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$ ]] && [[ $CUSTOM_DOMAIN != *.workers.dev ]] ||
    { echo "deploy: CUSTOM_DOMAIN is a host name of a zone in your account (for example 234.example.com), not a URL and not on workers.dev" >&2; exit 1; }
fi

wrangler="$root/node_modules/.bin/wrangler"
HOST_URL="https://$HOST_WORKER.$SUBDOMAIN.workers.dev"
CONNECTORS_URL="https://$CONNECTORS_WORKER.$SUBDOMAIN.workers.dev"
SANDBOX_URL="https://$SANDBOX_WORKER.$SUBDOMAIN.workers.dev"
CUSTOM_URL=${CUSTOM_DOMAIN:+https://$CUSTOM_DOMAIN}
OWNER_SECRETS="LLM_BASE_URL LLM_MODEL LLM_API_KEY"
AUTH_FILE=${AUTH_FILE:-$root/.env.auth.local}
AUTH_NAMES="FIREBASE_PROJECT_ID FIREBASE_API_KEY FIREBASE_AUTH_DOMAIN"
AUTH_ENABLED=""
TURNSTILE_FILE=${TURNSTILE_FILE:-$root/.env.turnstile.local}
TURNSTILE_ON=""

die() { echo "deploy: $*" >&2; exit 1; }
say() { echo "== $*"; }

auth_value() {  # NAME: the value of NAME in .env.auth.local with one pair of quotes removed; never echoed by the callers
  file_value "$AUTH_FILE" "$1"
}

file_value() {  # FILE NAME: the value of NAME in FILE with one pair of quotes removed; never echoed by the callers
  local line value
  line=$(grep -E "^[[:space:]]*$2=" "$1" | tail -1 || true)
  value=${line#*=}
  value=$(printf %s "$value" | tr -d '\r')
  value=${value#\"}; value=${value%\"}; value=${value#\'}; value=${value%\'}
  printf %s "$value"
}

auth_shape() {  # NAME value: whether the value looks like what NAME holds (the value is not printed)
  case "$1" in
    FIREBASE_PROJECT_ID) [[ $2 =~ ^[a-z][a-z0-9-]{4,29}$ ]] ;;
    FIREBASE_API_KEY) [[ $2 =~ ^[A-Za-z0-9_-]{20,80}$ ]] ;;
    FIREBASE_AUTH_DOMAIN) [[ $2 =~ ^[a-z0-9]([a-z0-9.-]*[a-z0-9])?\.[a-z]{2,}$ ]] ;;
  esac
}

load_auth() {  # sets AUTH_ENABLED=1 and FIREBASE_* when .env.auth.local is complete; says so; refuses a file with missing or malformed values
  AUTH_ENABLED=""
  if [ ! -f "$AUTH_FILE" ]; then say "sign-in with Google: off (no .env.auth.local)"; return 0; fi
  local name value problems=""
  for name in $AUTH_NAMES; do
    value=$(auth_value "$name")
    if [ -z "$value" ]; then problems="$problems $name(missing)"
    elif ! auth_shape "$name" "$value"; then problems="$problems $name(not the shape of a $name)"
    else printf -v "$name" %s "$value"; fi
  done
  [ -z "$problems" ] || die ".env.auth.local cannot turn sign-in on:$problems. Fix it or remove the file (docs/auth.md)"
  AUTH_ENABLED=1
  say "sign-in with Google: on (the three FIREBASE_ values of .env.auth.local, ACCOUNT_KEY generated once)"
}

auth_vars_line() {  # the lines that replace the marker in the host template: the three variables, or nothing
  [ -n "$AUTH_ENABLED" ] || return 0
  printf '"FIREBASE_PROJECT_ID": "%s", "FIREBASE_API_KEY": "%s", "FIREBASE_AUTH_DOMAIN": "%s",' "$FIREBASE_PROJECT_ID" "$FIREBASE_API_KEY" "$FIREBASE_AUTH_DOMAIN"
}

load_turnstile() {  # sets TURNSTILE_ON=1, TURNSTILE_SITE_KEY and TURNSTILE_SECRET from this stage's two lines of .env.turnstile.local; says so; refuses a malformed value
  TURNSTILE_ON=""
  local label=PRODUCTION site secret
  [ "$STAGE" = staging ] && label=STAGING
  if [ ! -f "$TURNSTILE_FILE" ]; then say "bot check (Turnstile): off (no .env.turnstile.local)"; return 0; fi
  site=$(file_value "$TURNSTILE_FILE" "TURNSTILE_${label}_SITE_KEY")
  secret=$(file_value "$TURNSTILE_FILE" "TURNSTILE_${label}_SECRET")
  if [ -z "$site$secret" ]; then say "bot check (Turnstile): off (.env.turnstile.local has no $STAGE keys)"; return 0; fi
  [[ $site =~ ^0x[0-9A-Za-z_-]{10,40}$ ]] || die "TURNSTILE_${label}_SITE_KEY in .env.turnstile.local is not the shape of a site key"
  [[ $secret =~ ^0x[0-9A-Za-z_-]{20,80}$ ]] || die "TURNSTILE_${label}_SECRET in .env.turnstile.local is missing or not the shape of a secret"
  TURNSTILE_SITE_KEY=$site TURNSTILE_SECRET=$secret TURNSTILE_ON=1
  say "bot check (Turnstile): on (the $STAGE site key and secret of .env.turnstile.local)"
}

turnstile_vars_line() {  # the line that replaces the marker in the host template: the public site key, or nothing
  [ -n "$TURNSTILE_ON" ] || return 0
  printf '"TURNSTILE_SITE_KEY": "%s",' "$TURNSTILE_SITE_KEY"
}

turnstile_secret_lines() {  # the host's TURNSTILE_SECRET, from the file, to the pipe that goes to wrangler (never printed)
  [ -n "$TURNSTILE_ON" ] || return 0
  printf 'TURNSTILE_SECRET=%s\n' "$TURNSTILE_SECRET"
}

filtered() {  # pattern command...: runs it quietly; on success shows the lines that match, on failure all of them
  local pattern=$1 out; shift
  out=$(mktemp)
  if "$@" > "$out" 2>&1; then
    grep -E "$pattern" "$out" || true
    rm -f "$out"
  else
    cat "$out" >&2; rm -f "$out"; return 1
  fi
}

worker_of() {  # host|connectors|sandbox: the Worker's name
  case "$1" in
    host) echo "$HOST_WORKER" ;; connectors) echo "$CONNECTORS_WORKER" ;; sandbox) echo "$SANDBOX_WORKER" ;;
    *) die "say host, connectors or sandbox" ;;
  esac
}

d1_id() {  # database name: its id, or nothing when it does not exist
  "$wrangler" d1 info "$1" --json < /dev/null 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin)["uuid"])' 2>/dev/null || true
}

routes_line() {  # the host's route on the custom domain, or nothing
  [ -z "$CUSTOM_DOMAIN" ] || printf '"routes": [{ "pattern": "%s", "custom_domain": true }],' "$CUSTOM_DOMAIN"
}

custom_domain_edits() {  # sed expressions: with a custom domain it is the canonical origin, and the workers.dev address is still accepted
  [ -n "$CUSTOM_DOMAIN" ] || return 0
  printf '%s\n' \
    "s|^\([[:space:]]*\"DJANGO_ALLOWED_HOSTS\": \"[^\"]*\)\"|\1,$CUSTOM_DOMAIN\"|" \
    "s|^\([[:space:]]*\"DJANGO_CSRF_TRUSTED_ORIGINS\": \"[^\"]*\)\"|\1,$CUSTOM_URL\"|" \
    "s|^\([[:space:]]*\"PUBLIC_BASE_URL\": \"\)https://$HOST_WORKER\.$SUBDOMAIN\.workers\.dev\"|\1$CUSTOM_URL\"|" \
    "s|^\([[:space:]]*\"HOST_PUBLIC_URL\": \"\)https://$HOST_WORKER\.$SUBDOMAIN\.workers\.dev\"|\1$CUSTOM_URL\"|" \
    "s|\(\"HOST_ORIGINS\": \"[^\"]*\)\"|\1,$CUSTOM_URL\"|"
}

render() {  # template output: the template with this file's names filled in
  [ -n "${AUTH_LOADED:-}" ] || { load_auth; AUTH_LOADED=1; }
  local ledger_id=${LEDGER_DB_ID:-} host_id=${HOST_DB_ID:-} edits
  [ -n "$ledger_id" ] || ledger_id=$(d1_id "$LEDGER_DB")
  [ -n "$host_id" ] || host_id=$(d1_id "$HOST_DB")
  [ -n "$ledger_id" ] && [ -n "$host_id" ] || die "the databases $LEDGER_DB and $HOST_DB do not both exist: run tools/deploy.sh init"
  edits=$(mktemp)
  custom_domain_edits > "$edits"
  sed -e "s|@HOST_WORKER@|$HOST_WORKER|g" -e "s|@CONNECTORS_WORKER@|$CONNECTORS_WORKER|g" \
    -e "s|@SANDBOX_WORKER@|$SANDBOX_WORKER|g" \
    -e "s|@HOST_DB@|$HOST_DB|g" -e "s|@HOST_DB_ID@|$host_id|g" \
    -e "s|@LEDGER_DB@|$LEDGER_DB|g" -e "s|@LEDGER_DB_ID@|$ledger_id|g" \
    -e "s|@SUBDOMAIN@|$SUBDOMAIN|g" -e "s|@RATE_LIMIT_NAMESPACE@|$RATE_LIMIT_NAMESPACE|g" \
    -e "s|@MCP_RATE_LIMIT_NAMESPACE@|$MCP_RATE_LIMIT_NAMESPACE|g" -e "s|@METRICS_DATASET@|$METRICS_DATASET|g" "$1" |
    sed -f "$edits" |
    sed -e "s|^\([[:space:]]*\)// @FIREBASE_VARS@\$|\1$(auth_vars_line)|" \
      -e "s|^\([[:space:]]*\)// @TURNSTILE_VARS@\$|\1$(turnstile_vars_line)|" \
      -e "s|^\([[:space:]]*\)// @ROUTES@\$|\1$(routes_line)|" > "$2"
  rm -f "$edits"
}

secrets_present() {  # worker: the names of the secrets it already has
  "$wrangler" secret list --name "$1" --format json < /dev/null 2>/dev/null |
    python3 -c 'import json,sys; print(" ".join(s["name"] for s in json.load(sys.stdin)))' 2>/dev/null || true
}

has_secret() { case " $(secrets_present "$1") " in *" $2 "*) return 0 ;; *) return 1 ;; esac; }

secret_lines() {  # worker names... : NAME=value for each secret the worker lacks, freshly generated; the values stay in the pipe
  local worker=$1 name; shift
  for name in "$@"; do
    has_secret "$worker" "$name" || printf '%s=%s\n' "$name" "$(openssl rand -hex 32)"
  done
}

require_clean_tree() {
  local dirty
  dirty=$(git -C "$root" status --porcelain)
  [ -z "$dirty" ] || { echo "$dirty" | head -15 >&2; die "the working tree has uncommitted changes; commit them first"; }
}

run_checks() {
  local dir
  for dir in checkout host; do
    say "checks in $dir"
    (cd "$root/$dir" && uv run ruff check . && uv run ruff format --check . && uv run pytest -q)
  done
  say "checks in sandbox"
  (cd "$root" && node --test sandbox/test/*.test.mjs)
  if [ "${CHECK_FULL:-}" = "1" ]; then "$root/tools/check.sh"; fi
}

upload() {  # dir: uploads the rendered config in dir; the secrets to add arrive on stdin (none: nothing is added)
  local dir=$1 pending tag options=()
  pending=$(cat)
  tag=$(git -C "$root" rev-parse --short HEAD)
  [ -z "$pending" ] || options=(--secrets-file /dev/stdin)
  cd "$root/$dir"
  if [ "$dir" = host ]; then  # the build of the home page (host/build_shell) gives it the policy these settings decide
    export SANDBOX_ORIGIN="$SANDBOX_URL"
    [ -z "$AUTH_ENABLED" ] || export FIREBASE_PROJECT_ID FIREBASE_API_KEY FIREBASE_AUTH_DOMAIN
    [ -z "$TURNSTILE_ON" ] || export TURNSTILE_SITE_KEY
  fi
  uv run pywrangler sync > /dev/null
  printf '%s' "$pending" | filtered "Uploaded|Deployed|https://|Version ID|Startup|Total Upload" \
    "$wrangler" deploy -c wrangler.deploy.jsonc --tag "$tag" --message "deploy $tag" ${options[@]+"${options[@]}"}
}

deploy_worker() {  # dir: renders the config and uploads it, with the secrets that arrive on stdin
  render "$root/$1/wrangler.public.jsonc" "$root/$1/wrangler.deploy.jsonc"
  (upload "$1")
}

deploy_sandbox() {  # the card sandbox: static JavaScript, no dependencies to sync, no database; a secret to add arrives on stdin
  local tag pending options=()
  pending=$(cat)
  tag=$(git -C "$root" rev-parse --short HEAD)
  [ -z "$pending" ] || options=(--secrets-file /dev/stdin)
  render "$root/sandbox/wrangler.public.jsonc" "$root/sandbox/wrangler.deploy.jsonc"
  (cd "$root/sandbox" && printf '%s' "$pending" | filtered "Uploaded|Deployed|https://|Version ID|Total Upload" \
    "$wrangler" deploy -c wrangler.deploy.jsonc --tag "$tag" --message "deploy $tag" ${options[@]+"${options[@]}"})
}

migrate_ledger() {
  say "ledger migrations"
  render "$root/checkout/wrangler.public.jsonc" "$root/checkout/wrangler.deploy.jsonc"
  (cd "$root/checkout" && printf 'y\n' | filtered "✅|No migrations|Error" "$wrangler" d1 migrations apply DB --remote -c wrangler.deploy.jsonc)
}

migrate_host() {  # ops-token: Django's migrations, run inside the host Worker (D1 is not reachable by manage.py)
  local ops=$1 code=""
  say "host migrations"
  for _ in $(seq 1 15); do
    code=$(curl -s -m 120 -o /dev/null -w '%{http_code}' -X POST "$HOST_URL/ops/migrate/" -H "authorization: Bearer $ops" || true)
    if [ "$code" = 200 ]; then echo "applied"; return 0; fi
    sleep 4
  done
  die "the host's migrations did not run (last status $code)"
}

ensure_host_exists() {  # the connectors bind to the host and the host to the connectors: on a first deploy one of them must exist first
  if "$wrangler" deployments list --name "$HOST_WORKER" > /dev/null 2>&1; then return 0; fi
  say "$HOST_WORKER does not exist yet: a placeholder of that name lets the connectors bind to it (the real host replaces it below)"
  local dir
  dir=$(mktemp -d)
  printf 'export default { fetch: () => new Response("not deployed yet", { status: 503 }) };\n' > "$dir/worker.js"
  printf '{ "name": "%s", "main": "worker.js", "compatibility_date": "2026-09-21" }\n' "$HOST_WORKER" > "$dir/wrangler.jsonc"
  (cd "$dir" && filtered "Uploaded|Deployed" "$wrangler" deploy -c wrangler.jsonc)
  rm -rf "$dir"
}

auth_secret_lines() {  # the host's ACCOUNT_KEY, made once when sign-in is on and the host lacks it (never rotated: it keeps every account's chats)
  [ -n "$AUTH_ENABLED" ] || return 0
  secret_lines "$HOST_WORKER" ACCOUNT_KEY
}

require_staged() {  # a production deploy is of a commit that staging already runs and passed its smoke test with
  [ "$STAGE" = production ] || return 0
  local head staged=""
  head=$(git -C "$root" rev-parse HEAD)
  [ ! -f "$STAGED_FILE" ] || staged=$(cat "$STAGED_FILE")
  [ "$staged" = "$head" ] && return 0
  [ "${SKIP_STAGING:-}" = 1 ] && { say "SKIP_STAGING=1: deploying a commit staging has not run"; return 0; }
  die "deploy $(git -C "$root" rev-parse --short HEAD) to staging first: STAGE=staging tools/deploy.sh"
}

deploy_all() {
  require_staged
  require_clean_tree
  load_auth; AUTH_LOADED=1
  load_turnstile
  run_checks
  local shared="" ops
  ops=$(openssl rand -hex 32)
  has_secret "$CONNECTORS_WORKER" MCP_ACCESS_TOKEN && has_secret "$HOST_WORKER" CHECKOUT_MCP_TOKEN || shared=$(openssl rand -hex 32)
  local events=""  # the key the host signs its MCP events subscriptions with: the host's own, made once
  has_secret "$HOST_WORKER" EVENTS_SECRET || events=$(openssl rand -hex 32)
  local pact=""  # the RSA key the host signs PACT delegation tokens and receipts with: the host's own, made once
  has_secret "$HOST_WORKER" PACT_SIGNING_KEY || pact=$(node "$root/tools/pact-key.mjs")
  local agent=""  # 234's own P-256 key as a personal agent at other Brands: the host's own, made once
  has_secret "$HOST_WORKER" PACT_AGENT_KEY || agent=$(node "$root/tools/pact-key.mjs" --ec)
  local signing=""  # the key the host signs a view's policy with: one value on the sandbox and the host, made again when either lacks it
  has_secret "$SANDBOX_WORKER" SIGNING_KEY && has_secret "$HOST_WORKER" SANDBOX_SIGNING_KEY || signing=$(openssl rand -hex 32)
  say "deploying $SANDBOX_WORKER (the card sandbox, first: the host's setting names it)"
  { [ -z "$signing" ] || echo "SIGNING_KEY=$signing"; } | deploy_sandbox
  migrate_ledger
  ensure_queues
  ensure_host_exists
  say "deploying $CONNECTORS_WORKER"
  { secret_lines "$CONNECTORS_WORKER" APPROVAL_SECRET; [ -z "$shared" ] || echo "MCP_ACCESS_TOKEN=$shared"; } \
    | deploy_worker checkout
  say "deploying $HOST_WORKER"
  { secret_lines "$HOST_WORKER" DJANGO_SECRET_KEY; auth_secret_lines; turnstile_secret_lines; [ -z "$shared" ] || echo "CHECKOUT_MCP_TOKEN=$shared"
    [ -z "$signing" ] || echo "SANDBOX_SIGNING_KEY=$signing"
    [ -z "$events" ] || echo "EVENTS_SECRET=$events"; [ -z "$pact" ] || echo "PACT_SIGNING_KEY='$pact'"
    [ -z "$agent" ] || echo "PACT_AGENT_KEY='$agent'"
    echo "OPS_TOKEN=$ops"; } | deploy_worker host
  migrate_host "$ops"
  smoke_test "$ops"
  if [ "$STAGE" = staging ]; then mkdir -p "$root/.stack" && git -C "$root" rev-parse HEAD > "$STAGED_FILE"; fi
}

http_status() { curl -s -m 60 -o /dev/null -w '%{http_code}' "$@" || true; }

header_of() {  # url name: the value of one response header (name in any case), without its line ending
  curl -s -m 30 -D - -o /dev/null "$1" | tr -d '\r' | grep -i "^$2:" | head -1 | cut -d: -f2- | sed 's/^ //' || true
}

smoke_auth() {  # cookie-jar csrf-token: sign-in is on exactly when .env.auth.local says so, and a garbage token is refused
  local jar=$1 csrf=$2 page headers me
  page=$(curl -s -m 60 "$HOST_URL/" || true)
  me=$(curl -s -m 60 -b "$jar" "$HOST_URL/api/me" || true)
  headers=$(curl -s -m 30 -D - -o /dev/null "$HOST_URL/" | tr -d '\r' || true)
  if [ -n "$AUTH_ENABLED" ]; then
    check "sign-in: the home page holds the account part of the drawer" "$(grep -c '<chat-account' <<< "$page" || true)" 1
    check "sign-in: /api/me carries the Firebase web app's public identifiers" "$(grep -c '"signIn": {"apiKey"' <<< "$me" || true)" 1
    check "sign-in: /auth/session refuses a garbage token" "$(curl -s -m 60 -b "$jar" -o /dev/null -w '%{http_code}' -X POST "$HOST_URL/auth/session" \
      -H "origin: $HOST_URL" -H "referer: $HOST_URL/" -H "X-CSRFToken: $csrf" -H 'content-type: application/json' -d '{"idToken":"garbage"}' || true)" 401
    check "sign-in: /auth/session needs the CSRF token" "$(curl -s -m 60 -b "$jar" -o /dev/null -w '%{http_code}' -X POST "$HOST_URL/auth/session" \
      -H "origin: $HOST_URL" -H 'content-type: application/json' -d '{"idToken":"garbage"}' || true)" 403
    check "sign-in: the popup keeps its link to the page (COOP)" "$(grep -ci '^cross-origin-opener-policy: same-origin-allow-popups' <<< "$headers" || true)" 1
    check "sign-in: only apis.google.com is added to script-src" "$(grep -ci "script-src 'self' https://apis.google.com;" <<< "$headers" || true)" 1
    check "pact: the card offers delegation" "$(curl -s -m 30 "$HOST_URL/a2a/234/.well-known/agent-card.json" | grep -c '"userDelegation"' || true)" 1
    check "pact: the delegation key is published, the public half only" "$(curl -s -m 30 "$HOST_URL/a2a/234/oauth/jwks.json" | grep -c '"kty": "RSA"' || true)$(curl -s -m 30 "$HOST_URL/a2a/234/oauth/jwks.json" | grep -c '"d":' || true)" 10
    check "pact: device authorization needs the agent's token" "$(http_status -X POST "$HOST_URL/a2a/234/oauth/device_authorization" \
      -H 'content-type: application/x-www-form-urlencoded' -d 'client_id=https://x.example&scope=payments')" 401
  else
    check "sign-in is off: no account part on the page" "$(grep -c '<chat-account' <<< "$page" || true)" 0
    check "sign-in is off: /api/me names no Firebase app" "$(grep -c '"signIn": null' <<< "$me" || true)" 1
    check "sign-in is off: /auth/session does not exist" "$(curl -s -m 60 -b "$jar" -o /dev/null -w '%{http_code}' -X POST "$HOST_URL/auth/session" \
      -H "origin: $HOST_URL" -H "referer: $HOST_URL/" -H "X-CSRFToken: $csrf" -H 'content-type: application/json' -d '{}' || true)" 404
    check "sign-in is off: COOP is same-origin" "$(grep -ci '^cross-origin-opener-policy: same-origin$' <<< "$headers" || true)" 1
  fi
}

smoke_shell() {  # the home page is a static asset (no Worker, no cookie) under the headers every other page has
  local headers
  headers=$(curl -s -m 30 -D - -o /dev/null "$HOST_URL/" | tr -d '\r' || true)
  check "the home page is served by the assets: it sets no cookie and does not vary" "$(grep -ciE '^(set-cookie|vary):' <<< "$headers" || true)" 0
  check "the home page's policy is the one every page of the Worker has" "$(header_of "$HOST_URL/" content-security-policy)" "$(header_of "$HOST_URL/manifest.webmanifest" content-security-policy)"
  check "the home page is not framed, not sniffed, and sends no referrer elsewhere" "$(grep -ciE '^(x-frame-options: DENY|x-content-type-options: nosniff|referrer-policy: same-origin)$' <<< "$headers" || true)" 3
  check "the home page is cached for a minute and revalidated" "$(grep -ci '^cache-control: public, max-age=60, must-revalidate$' <<< "$headers" || true)" 1
  check "/api/me is never stored" "$(header_of "$HOST_URL/api/me" cache-control)" "no-store, private"
  check "/api/me refuses a request that comes from another site" "$(curl -s -m 30 -o /dev/null -w '%{http_code}' -H 'Sec-Fetch-Site: cross-site' "$HOST_URL/api/me" || true)" 403
}

smoke_custom() {  # the host on its custom domain: page, /api/me, cookies, the sandbox framing it, and the workers.dev address still answering
  local origin=$CUSTOM_URL waited=0 jar token stranger=https://evil.example
  say "the custom domain $CUSTOM_DOMAIN (a new one can take a few minutes to get its certificate)"
  while [ "$(http_status "$origin/api/me")" != 200 ] && [ "$waited" -lt 300 ]; do sleep 10; waited=$((waited + 10)); done
  jar=$(mktemp)
  check "custom domain: the home page" "$(http_status "$origin/")" 200
  check "custom domain: /api/me" "$(http_status -c "$jar" "$origin/api/me")" 200
  check "custom domain: the home page has the policy of the workers.dev address" "$(header_of "$origin/" content-security-policy)" "$(header_of "$HOST_URL/" content-security-policy)"
  check "custom domain: its cookies are its own (none names a Domain)" "$(curl -s -m 30 -D - -o /dev/null "$origin/api/me" | grep -i '^set-cookie:' | grep -ci 'domain=' || true)" 0
  token=$(grep -o '"csrf": "[^"]*' <(curl -s -m 60 -b "$jar" "$origin/api/me") | cut -d'"' -f4 || true)
  check "custom domain: its own origin is trusted for a POST (an empty message is refused as empty, not as forged)" "$(curl -s -m 60 -b "$jar" -o /dev/null -w '%{http_code}' -X POST "$origin/c/$(openssl rand -hex 16)/start" \
    -H "origin: $origin" -H "referer: $origin/" -H "X-CSRFToken: $token" -H 'content-type: application/json' -d '{"text":""}' || true)" 422
  check "custom domain: a POST that names another origin is refused as forged" "$(curl -s -m 60 -b "$jar" -o /dev/null -w '%{http_code}' -X POST "$origin/c/$(openssl rand -hex 16)/start" \
    -H "origin: $stranger" -H "referer: $stranger/" -H "X-CSRFToken: $token" -H 'content-type: application/json' -d '{"text":""}' || true)" 403
  check "custom domain: the sandbox frames pages of that origin" "$(http_status "$SANDBOX_URL/?host=$origin")" 200
  check "custom domain: and names it alone as its embedder" "$(curl -s -m 30 -D - -o /dev/null "$SANDBOX_URL/?host=$origin" | tr -d '\r' | grep -Eci "frame-ancestors $origin(;|$)" || true)" 1
  check "custom domain: and still refuses a page on any other origin" "$(http_status "$SANDBOX_URL/?host=$stranger")" 403
  check "custom domain: the workers.dev address still answers, with no redirect" "$(http_status "$HOST_URL/api/me")/$(curl -s -m 30 -o /dev/null -w '%{redirect_url}' "$HOST_URL/")" "200/"
  rm -f "$jar"
}

smoke_test() {  # [ops-token]: the deploy's own, which lets the smoke test's first message past the bot check
  say "smoke test (curl only; it sends one word, so with a model set that is one model call)"
  local jar failures=0 csrf chat page
  jar=$(mktemp)
  check() { if [ "$2" = "$3" ]; then echo "ok   $1"; else echo "FAIL $1: expected $3, got $2"; failures=$((failures + 1)); fi; }
  check "sandbox /health" "$(http_status "$SANDBOX_URL/health")" 200
  check "sandbox proxy page for the host" "$(http_status "$SANDBOX_URL/?host=$HOST_URL")" 200
  check "sandbox refuses a page that is not the host" "$(http_status "$SANDBOX_URL/?host=https://evil.example")" 403
  check "sandbox proxy names only the host as its embedder" "$(curl -s -m 30 -D - -o /dev/null "$SANDBOX_URL/?host=$HOST_URL" | tr -d '\r' | grep -Eci "frame-ancestors $HOST_URL(;|$)" || true)" 1
  check "sandbox serves no view under a policy the host did not sign" "$(http_status "$SANDBOX_URL/view?host=$HOST_URL&csp=%7B%22connectDomains%22%3A%5B%22https%3A%2F%2Fevil.example.com%22%5D%7D&sig=$(printf '0%.0s' $(seq 64))")" 403
  check "sandbox sets no cookie" "$(curl -s -m 30 -D - -o /dev/null "$SANDBOX_URL/?host=$HOST_URL" | grep -ci '^set-cookie' || true)" 0
  check "connectors /health" "$(http_status "$CONNECTORS_URL/health")" 200
  check "connectors tools/list without the token" "$(http_status -X POST "$CONNECTORS_URL/paystack-pay/mcp" \
    -H 'content-type: application/json' -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}')" 401
  check "connectors /test routes are off" "$(http_status "$CONNECTORS_URL/test/summary")" 404
  check "connectors refuse a Paystack webhook without Paystack's signature" "$(http_status -X POST "$CONNECTORS_URL/hooks/paystack" \
    -H 'content-type: application/json' -d '{"event":"charge.success","data":{"reference":"x"}}')" 401
  check "connectors answer a VTpass webhook as VTpass asks" "$(curl -s -m 60 -X POST "$CONNECTORS_URL/hooks/vtpass" \
    -H 'content-type: application/json' -d '{"type":"transaction-update","data":{}}' || true)" '{"response": "success"}'
  check "the host refuses an unsigned MCP event" "$(http_status -X POST "$HOST_URL/hooks/events" \
    -H 'content-type: application/json' -d '{"type":"verification","challenge":"x"}')" 401
  check "host page" "$(http_status "$HOST_URL/")" 200
  smoke_shell
  check "the host's page frames only the sandbox" "$(curl -s -m 30 -D - -o /dev/null "$HOST_URL/" | tr -d '\r' | grep -ciE "frame-src $SANDBOX_URL( https://[a-z0-9-]+\\.firebaseapp\\.com)?;" || true)" 1
  check "the host's cookies are the host's alone (none names a Domain)" "$(grep -ci 'domain=' <(curl -s -m 30 -D - -o /dev/null -c "$jar" "$HOST_URL/api/me") || true)" 0
  csrf=$(grep -o '"csrf": "[^"]*' <(curl -s -m 60 -b "$jar" -c "$jar" "$HOST_URL/api/me") | cut -d'"' -f4 || true)
  chat=$(openssl rand -hex 16)
  if [ -n "$TURNSTILE_ON" ]; then
    check "the bot check is on: /api/me offers the widget" "$(if curl -s -m 30 -b "$jar" "$HOST_URL/api/me" | grep -q "\"botCheck\": \"$TURNSTILE_SITE_KEY\""; then echo yes; else echo no; fi)" yes
    check "the bot check is on: a first message with no token is refused" "$(curl -s -m 60 -b "$jar" -o /dev/null -w '%{http_code}' -X POST "$HOST_URL/c/$(openssl rand -hex 16)/start" \
      -H "origin: $HOST_URL" -H "referer: $HOST_URL/" -H "X-CSRFToken: $csrf" -H 'content-type: application/json' -d '{"text":"hi"}' || true)" 403
  fi
  started=$(curl -s -m 60 -b "$jar" -c "$jar" -o /dev/null -w '%{http_code}' -X POST "$HOST_URL/c/$chat/start" \
    -H "origin: $HOST_URL" -H "referer: $HOST_URL/" -H "X-CSRFToken: $csrf" -H 'content-type: application/json' \
    ${1:+-H "Authorization: Bearer $1"} -d '{"text":"hi"}' || true)
  check "a chat is started by its first message" "$started" 200
  page=$(curl -s -m 10 -b "$jar" "$HOST_URL/c/$chat/events" || true)
  check "the turn ran and reached the connectors" "$(if grep -q 'could not be reached' <<< "$page"; then echo no; else echo yes; fi)" yes
  check "the log answered" "$(if [ -n "$page" ]; then echo yes; else echo no; fi)" yes
  check "no stack trace" "$(if grep -q 'Traceback' <<< "$page"; then echo trace; else echo none; fi)" none
  smoke_auth "$jar" "$csrf"
  [ -z "$CUSTOM_DOMAIN" ] || smoke_custom
  rm -f "$jar"
  [ "$failures" -eq 0 ] || die "$failures smoke checks failed"
}

# The connectors' Queues (wrangler.public.jsonc): rechecks a provider webhook asks for, and event deliveries,
# each with a dead-letter queue. Made once; a deploy needs them before the connectors' consumers can bind.
QUEUES="$CONNECTORS_WORKER-provider-jobs $CONNECTORS_WORKER-provider-jobs-dlq $CONNECTORS_WORKER-event-jobs $CONNECTORS_WORKER-event-jobs-dlq"

ensure_queues() {
  local queue
  for queue in $QUEUES; do
    "$wrangler" queues info "$queue" > /dev/null 2>&1 || filtered "Created|created" "$wrangler" queues create "$queue"
  done
}

cmd_init() {
  local name
  for name in "$LEDGER_DB" "$HOST_DB"; do
    if [ -n "$(d1_id "$name")" ]; then echo "$name exists"; else filtered "Success|Created" "$wrangler" d1 create "$name"; fi
  done
  ensure_queues
}

cmd_secret() {  # host|connectors NAME: the value comes on stdin, loses one pair of quotes, and is put without being shown
  local target=$1 name=$2 value allowed=""
  [ "$target" = host ] && allowed=$OWNER_SECRETS
  case " $allowed " in *" $name "*) ;; *) die "$name is not a secret to set by hand on $target (the owner's are $OWNER_SECRETS, on the host)" ;; esac
  value=$(tr -d '\r\n')
  value=${value#\"}; value=${value%\"}; value=${value#\'}; value=${value%\'}
  [ -n "$value" ] || die "nothing came on stdin for $name (did grep find the line?): nothing was set"
  if [ "$name" = LLM_MODEL ]; then
    case "$(tr '[:upper:]' '[:lower:]' <<< "$value")" in *claude*|*anthropic*) die "a Claude model is not used here" ;; esac
  fi
  printf %s "$value" | put_secret "$(worker_of "$target")" "$name"
}

put_secret() {  # worker name: the value comes on stdin
  filtered "Success|rror" "$wrangler" secret put "$2" --name "$1"
}

cmd_upload() {  # host|connectors|sandbox
  require_clean_tree
  load_auth; AUTH_LOADED=1
  case "$1" in
    host) auth_secret_lines | deploy_worker host ;;
    connectors) deploy_worker checkout < /dev/null ;;
    sandbox) deploy_sandbox < /dev/null ;;
    *) die "say host, connectors or sandbox" ;;
  esac
}

cmd_rotate() {
  local value; value=$(openssl rand -hex 32)
  case "$1" in
    token) printf %s "$value" | put_secret "$CONNECTORS_WORKER" MCP_ACCESS_TOKEN
           printf %s "$value" | put_secret "$HOST_WORKER" CHECKOUT_MCP_TOKEN ;;
    DJANGO_SECRET_KEY) printf %s "$value" | put_secret "$HOST_WORKER" "$1"; cmd_upload host ;;
    EVENTS_SECRET) printf %s "$value" | put_secret "$HOST_WORKER" "$1"; cmd_upload host ;;
    PACT_SIGNING_KEY) node "$root/tools/pact-key.mjs" | put_secret "$HOST_WORKER" "$1"; cmd_upload host ;;
    PACT_AGENT_KEY) node "$root/tools/pact-key.mjs" --ec | put_secret "$HOST_WORKER" "$1"; cmd_upload host ;;
    APPROVAL_SECRET) printf %s "$value" | put_secret "$CONNECTORS_WORKER" "$1" ;;
    SANDBOX_SIGNING_KEY) printf %s "$value" | put_secret "$SANDBOX_WORKER" SIGNING_KEY
                         printf %s "$value" | put_secret "$HOST_WORKER" "$1" ;;
    *) die "rotate token, DJANGO_SECRET_KEY, EVENTS_SECRET, PACT_SIGNING_KEY, PACT_AGENT_KEY, APPROVAL_SECRET or SANDBOX_SIGNING_KEY" ;;
  esac
}

cmd_auth() {  # what .env.auth.local holds, by name, and what a deploy would do: no value is printed
  local name value
  if [ ! -f "$AUTH_FILE" ]; then
    echo "no .env.auth.local: a deploy leaves sign-in off. Its lines are NAME=value for: $AUTH_NAMES (docs/auth.md)"; return 0
  fi
  for name in $AUTH_NAMES; do
    value=$(auth_value "$name")
    if [ -z "$value" ]; then echo "$name  missing"; elif auth_shape "$name" "$value"; then echo "$name  set"; else echo "$name  set, but not the shape of a $name"; fi
  done
  load_auth
  if has_secret "$HOST_WORKER" ACCOUNT_KEY; then echo "ACCOUNT_KEY  already on $HOST_WORKER (kept)"; else echo "ACCOUNT_KEY  a deploy generates it once"; fi
}

cmd_names() {
  cat <<EOF
stage              $STAGE
sandbox Worker     $SANDBOX_WORKER     $SANDBOX_URL
host Worker        $HOST_WORKER        $HOST_URL
custom domain      $( [ -n "$CUSTOM_DOMAIN" ] && echo "$CUSTOM_URL (canonical; $HOST_URL still answers)" || echo "none (CUSTOM_DOMAIN is not set)")
connectors Worker  $CONNECTORS_WORKER  $CONNECTORS_URL
host database      $HOST_DB
ledger database    $LEDGER_DB
rate limit         namespace $RATE_LIMIT_NAMESPACE (chat), $MCP_RATE_LIMIT_NAMESPACE (MCP gateway)
metrics            Analytics Engine dataset $METRICS_DATASET
sign-in            $( [ -f "$AUTH_FILE" ] && echo "$(basename "$AUTH_FILE") found: tools/deploy.sh auth says what it holds" || echo "off (no $(basename "$AUTH_FILE"))")
EOF
}

cmd_destroy() {
  local typed
  read -r -p "This deletes $HOST_WORKER, $CONNECTORS_WORKER, $SANDBOX_WORKER, $HOST_DB and $LEDGER_DB with everything in them. Type $HOST_WORKER to go on: " typed
  [ "$typed" = "$HOST_WORKER" ] || die "not confirmed; nothing was deleted"
  printf 'y\n' | "$wrangler" delete "$HOST_WORKER" --force || true
  printf 'y\n' | "$wrangler" delete "$CONNECTORS_WORKER" --force || true
  printf 'y\n' | "$wrangler" delete "$SANDBOX_WORKER" --force || true
  "$wrangler" d1 delete "$HOST_DB" --skip-confirmation || true
  "$wrangler" d1 delete "$LEDGER_DB" --skip-confirmation || true
}

cmd=${1:-deploy}
case "$cmd" in
  deploy) deploy_all ;;
  init) cmd_init ;;
  secret) [ $# -eq 3 ] || die "usage: tools/deploy.sh secret host NAME < value"; cmd_secret "$2" "$3" ;;
  rotate) cmd_rotate "${2:?what to rotate}" ;;
  upload) cmd_upload "${2:?host, connectors or sandbox}" ;;
  names) cmd_names ;;
  render) render "${2:?template}" "${3:?output}" ;;
  auth) cmd_auth ;;
  destroy) cmd_destroy ;;
  versions) "$wrangler" versions list --name "$(worker_of "${2:?host, connectors or sandbox}")" ;;
  rollback) "$wrangler" rollback --name "$(worker_of "${2:?host, connectors or sandbox}")" --yes --message "${3:-rollback}" ;;
  tail) "$wrangler" tail "$(worker_of "${2:?host, connectors or sandbox}")" --format pretty ;;
  *) die "unknown command $cmd (see the top of this file)" ;;
esac
