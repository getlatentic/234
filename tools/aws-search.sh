#!/bin/bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# 234's web search on the owner's AWS account (docs/web.md): an AgentCore Gateway with the managed Web Search tool,
# and one IAM user that may invoke that gateway and nothing else (infra/aws/web-search.yaml, us-east-1).
#
#   AWS_PROFILE=name tools/aws-search.sh up        makes or updates the stack, and says the gateway's address
#   AWS_PROFILE=name tools/aws-search.sh key       makes the caller's access key and keeps it in .env.search.local
#                                                  (mode 600, git-ignored); it prints no part of it
#   [STAGE=staging] tools/aws-search.sh secrets    puts the address and the key into the connectors Worker's
#                                                  secrets, from that file, and deploys nothing
#   AWS_PROFILE=name tools/aws-search.sh down      deletes the key and the stack
# The one-time cost is nothing; a search is $0.007 and a person has a few a day (SEARCHES_PER_DAY).
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
stack=${SEARCH_STACK:-ask234-web-search}
region=us-east-1
file=${SEARCH_FILE:-$root/.env.search.local}
aws_() { aws --region "$region" ${AWS_PROFILE:+--profile "$AWS_PROFILE"} "$@"; }
say() { echo "== $*"; }
die() { echo "!! $*" >&2; exit 1; }

output() {  # name: one output of the stack
  aws_ cloudformation describe-stacks --stack-name "$stack" --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text
}

cmd_up() {
  say "stack $stack in $region"
  aws_ cloudformation deploy --stack-name "$stack" --template-file "$root/infra/aws/web-search.yaml" \
    --capabilities CAPABILITY_NAMED_IAM --no-fail-on-empty-changeset
  say "gateway: $(output GatewayUrl)"
}

cmd_key() {
  local user url count id secret
  user=$(output CallerName); url=$(output GatewayUrl)
  [ -n "$user" ] && [ "$user" != None ] || die "no stack $stack: run up first"
  [ ! -e "$file" ] || die "$file exists; delete the key it holds (see down) and the file before making another"
  count=$(aws_ iam list-access-keys --user-name "$user" --query 'length(AccessKeyMetadata)' --output text)
  [ "$count" -lt 2 ] || die "$user already has two access keys"
  umask 077
  read -r id secret < <(aws_ iam create-access-key --user-name "$user" --query 'AccessKey.[AccessKeyId,SecretAccessKey]' --output text)
  printf 'SEARCH_GATEWAY_URL=%s\nAWS_ACCESS_KEY_ID=%s\nAWS_SECRET_ACCESS_KEY=%s\n' "$url" "$id" "$secret" > "$file"
  say "key ${id:0:4}... kept in $file (mode 600)"
}

cmd_secrets() {
  [ -f "$file" ] || die "no $file: run key first"
  for name in SEARCH_GATEWAY_URL AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY; do
    grep "^$name=" "$file" | cut -d= -f2- | "$root/tools/deploy.sh" secret connectors "$name"
  done
  say "set on the connectors Worker; the next deploy of it (or a version upload) reads them"
}

cmd_down() {
  local user
  user=$(output CallerName)
  if [ -n "$user" ] && [ "$user" != None ]; then
    for id in $(aws_ iam list-access-keys --user-name "$user" --query 'AccessKeyMetadata[].AccessKeyId' --output text); do
      aws_ iam delete-access-key --user-name "$user" --access-key-id "$id"
    done
  fi
  aws_ cloudformation delete-stack --stack-name "$stack"
  aws_ cloudformation wait stack-delete-complete --stack-name "$stack"
  rm -f "$file"
  say "deleted; the connectors Worker still holds the three secrets: delete them with wrangler secret delete"
}

case "${1:-}" in
  up) cmd_up ;;
  key) cmd_key ;;
  secrets) cmd_secrets ;;
  down) cmd_down ;;
  *) sed -n '3,12p' "$0"; exit 2 ;;
esac
