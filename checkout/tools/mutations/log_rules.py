# SPDX-License-Identifier: AGPL-3.0-or-later
"""What a log line holds (host turns/logs.py, turns/trace.py, turns/hub.py; connectors audit.py, http.py): a
secret or a full account number never reaches a line, a traceback is scrubbed, and one task id follows a turn
to the connectors. Run against the host's own tests, and the connectors' for the audit."""

from tools.mutations.model import Mutation
from tools.mutations.model import host_mutation as host

LOGS = ["tests/test_logs.py"]

MUTATIONS: list[Mutation] = [
    host(
        "logs: a message is scrubbed",
        "turns/logs.py",
        "record.msg, record.args = scrub(record.getMessage()), None",
        "record.msg, record.args = record.getMessage(), None",
        LOGS,
    ),
    host(
        "logs: a traceback is scrubbed",
        "turns/logs.py",
        "record.exc_text = scrub(_plain.formatException(record.exc_info))",
        "record.exc_text = _plain.formatException(record.exc_info)",
        LOGS,
    ),
    host(
        "logs: a long digit run is masked",
        "turns/logs.py",
        "return _LONG_DIGITS.sub(lambda m: _mask(m.group()), scrubbed(kept, links=True))",
        "return scrubbed(kept, links=True)",
        LOGS,
    ),
    host(
        "logs: a link loses its credentials and query",
        "turns/logs.py",
        '    kept = _LINK_PRIVATE.sub("", text)',
        "    kept = text",
        LOGS,
    ),
    host(
        "logs: the task id travels to the connectors",
        "turns/hub.py",
        "                headers[TASK_HEADER] = task",
        "                pass",
        ["tests/test_logs.py", "tests/test_hub.py"],
    ),
]
