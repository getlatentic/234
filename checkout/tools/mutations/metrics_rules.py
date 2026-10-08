# SPDX-License-Identifier: AGPL-3.0-or-later
"""What 234 records about how it runs (host turns/metrics.py, turns/health.py): every finished turn and every
tool call is a data point, recording never fails a turn, and a health check that fails is recorded, not
raised. Run against the host's own tests."""

from tools.mutations.model import Mutation
from tools.mutations.model import host_mutation as host

METRICS = ["tests/test_metrics.py"]

MUTATIONS: list[Mutation] = [
    host(
        "metrics: a finished turn is a data point",
        "turns/runner.py",
        '        self._record(events, turn, reason, str(marks.get("cause", "")))',
        "        pass",
        METRICS,
    ),
    host(
        "metrics: every tool call is a data point",
        "turns/tool_calls.py",
        "        self._metrics.tool(outcome.server, outcome.tool, measured, self._clock() - began)",
        "        pass",
        METRICS,
    ),
    host(
        "metrics: recording that fails never fails the turn",
        "turns/metrics.py",
        '        except Exception:\n            log.warning("A %s data point could not be written"',
        '        except ZeroDivisionError:\n            log.warning("A %s data point could not be written"',
        METRICS,
    ),
    host(
        "metrics: a health check that fails is recorded, not raised",
        "turns/health.py",
        "            passed[part] = False",
        "            raise",
        METRICS,
    ),
]
