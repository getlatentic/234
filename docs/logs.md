# What the logs say

Every log line of the host is one JSON object: `ts`, `level`, `logger`, `msg`, and, while a turn runs,
`chat`, `owner` and `task`. Code: `host/src/turns/logs.py` (the filter and the formatter) and
`host/src/turns/trace.py` (what a turn binds). The connectors' audit lines (`checkout/src/checkout/audit.py`)
carry `task` and `owner` the same way.

## One id per turn

- `chat` is the chat id; `owner` is twelve hex characters of a SHA-256 of its owner, so one person's lines can
  be told from another's and nobody can be read back; `task` is the turn's id.
- The host sends the task id to the connectors in the `x-task-id` header (`turns/hub.py`); the connectors
  bind it for the length of the call (`owner.py`, `http.py`), so one id follows a turn through all three Workers.
  A header that is not an id (letters, digits, `_`, `-`, up to 64) is dropped, not refused: it only labels lines.

## What a line never holds

One filter, on the console handler, scrubs every record the host writes, ours and the libraries': the message,
a traceback, and each text field.

- keys, bearer tokens, labelled secrets, one-time codes, long secrets and card numbers
  (`turns/compaction/scrub.py`, the wall before the summariser);
- digit runs of seven or more, shortened to the first four and last three (as the connectors' audit);
- a link's credentials, query and fragment (its origin and path stay).

`tests/test_logs.py` raises an exception that carries an account number and a key, logs both, and checks
neither is in any line.

## Events

| `msg` | When | Fields |
|---|---|---|
| `round` | each model round | `finish_reason`, `tool_calls`, `prompt_tokens`, `completion_tokens`, `duration_ms` |
| `tool` | each tool call of the model | `server`, `tool`, `outcome`, `duration_ms`, `is_error`, `code` (the refusal code, e.g. `LIMIT_EXCEEDED`) |

The tool event of the chat log also carries `duration_ms` and `code`. The finish-reason mix is the count of
`round` lines by `finish_reason`.
