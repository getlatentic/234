#!/bin/bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# Kills a host Worker outright (SIGKILL, as a crash would) and starts it again on the same state, for the
# crash test. usage: [WATCHDOG_SECONDS=8] tools/restart-host.sh do|queue|waituntil
source "$(dirname "$0")/stack.sh"
stop_host "$1"
start_host "$1"
