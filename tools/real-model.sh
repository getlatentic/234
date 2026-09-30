#!/bin/bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# Runs the host against a real model, for the owner to try (nothing here reads a secret from disk or prints one).
#
#   export LLM_BASE_URL=https://.../v1      an OpenAI-compatible chat completions endpoint
#   export LLM_MODEL=openai.gpt-oss-120b    never a Claude model
#   export LLM_API_KEY=...
#   tools/real-model.sh                      starts the stack (host on http://localhost:8901)
#   tools/real-model.sh probe [N] [WORDS]    also sends each probe prompt (only those containing WORDS) N times
#                                            (default 5) and reports, per prompt, the calls with a missing field,
#                                            the asks and the right quotes, and every round's finish_reason
#                                            (host/tests/real_probe.py)
#   PORT_BASE=8920 picks the ports (host on PORT_BASE+1)
#   tools/real-model.sh compaction [N]       also runs N long chats (default 5, 150 turns each, about twelve minutes) and reports
#                                            what compaction kept and cost (host/tests/compaction_probe.py); start it with
#                                            VISITOR_CAP=5000 and a small context window (docs/compaction.md)
#   tools/down.sh                            stops it and removes the key file
#
# The host sends tool_choice "auto" and reasoning_effort "low" and no output ceiling (see turns/model.py).
set -e
root=$(cd "$(dirname "$0")/.." && pwd)
: "${LLM_BASE_URL:?set LLM_BASE_URL}" "${LLM_MODEL:?set LLM_MODEL}" "${LLM_API_KEY:?set LLM_API_KEY}"
case "$(echo "$LLM_MODEL" | tr '[:upper:]' '[:lower:]')" in *claude*|*anthropic*) echo "A Claude model is not used here."; exit 1 ;; esac
umask 077
# The host's own dummy secrets stay as they are; the model key is replaced by yours, in a file git ignores.
grep -v '^LLM_API_KEY=' "$root/host/.dev.vars" > "$root/host/.dev.vars.real"
printf 'LLM_API_KEY=%s\n' "$LLM_API_KEY" >> "$root/host/.dev.vars.real"
REAL_MODEL=1 "$root/tools/up.sh"
if [ "${1:-}" = "probe" ]; then
  (cd "$root/host" && HOST_URL="http://localhost:$((${PORT_BASE:-8900} + 1))" PYTHONPATH=src uv run python -u -m tests.real_probe "${2:-5}" "${3:-}")
fi
if [ "${1:-}" = "compaction" ]; then
  (cd "$root/host" && HOST_URL="http://localhost:$((${PORT_BASE:-8900} + 1))" PYTHONPATH=src uv run python -u -m tests.compaction_probe "${2:-5}")
fi
