#!/bin/bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# 234's web search on the owner's AWS account (docs/web.md): an AgentCore Gateway with the managed Web Search tool,
# and one IAM user that may invoke that gateway and nothing else (infra/aws/terraform, us-east-1).
#
#   AWS_PROFILE=name tools/aws-search.sh plan      says what up would change, and changes nothing
#   AWS_PROFILE=name tools/aws-search.sh up        makes or updates it (terraform apply), and says the gateway's address
#   AWS_PROFILE=name tools/aws-search.sh key       makes the caller's access key and keeps it in .env.search.local
#                                                  (mode 600, git-ignored); it prints no part of it
#   [STAGE=staging] tools/aws-search.sh secrets    puts the address and the key into the connectors Worker's
#                                                  secrets, from that file, and deploys nothing
#   AWS_PROFILE=name tools/aws-search.sh down      deletes the key and everything up made (terraform destroy)
# The one-time cost is nothing; a search is $0.007 and a person has a few a day (SEARCHES_PER_DAY).
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
tf="$root/infra/aws/terraform"
region=us-east-1
file=${SEARCH_FILE:-$root/.env.search.local}
aws_() { aws --region "$region" ${AWS_PROFILE:+--profile "$AWS_PROFILE"} "$@"; }
say() { echo "== $*"; }
die() { echo "!! $*" >&2; exit 1; }

terraform_() { terraform -chdir="$tf" "$@"; }

output() {  # name: one output, or nothing when nothing has been made
  terraform_ output -raw "$1" 2>/dev/null || true
}

cmd_plan() {
  terraform_ init -input=false > /dev/null
  terraform_ plan -input=false
}

cmd_up() {
  say "terraform in infra/aws/terraform ($region)"
  terraform_ init -input=false > /dev/null
  terraform_ apply -input=false -auto-approve
  say "gateway: $(output gateway_url)"
}

cmd_key() {
  local user url count id secret
  user=$(output caller_name); url=$(output gateway_url)
  [ -n "$user" ] || die "nothing made yet: run up first"
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
  user=$(output caller_name)
  if [ -n "$user" ]; then
    for id in $(aws_ iam list-access-keys --user-name "$user" --query 'AccessKeyMetadata[].AccessKeyId' --output text); do
      aws_ iam delete-access-key --user-name "$user" --access-key-id "$id"
    done
  fi
  terraform_ destroy -input=false -auto-approve
  rm -f "$file"
  say "deleted; the connectors Worker still holds the three secrets: delete them with wrangler secret delete"
}

case "${1:-}" in
  plan) cmd_plan ;;
  up) cmd_up ;;
  key) cmd_key ;;
  secrets) cmd_secrets ;;
  down) cmd_down ;;
  *) sed -n '3,14p' "$0"; exit 2 ;;
esac
