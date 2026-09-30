#!/bin/bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# Stops the local stack started by up.sh on the same PORT_BASE, and nothing else.
source "$(dirname "$0")/stack.sh"
stop_stack
rm -f "$root/host/.dev.vars.real"
[ "${1:-}" = "quiet" ] || echo "down (ports $base-$((base + 19)))"
