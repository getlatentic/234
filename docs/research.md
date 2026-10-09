# Research that runs on its own

A question that needs several searches or pages ("what does it take to renew a licence, and what does it cost
at each step") is handed to a run of its own. The chat answers at once that it started, and the report arrives
in the chat later, as an event the model answers. Code: `host/src/turns/research/`.

## How a run works

- The model calls `start_research(question)` (the host serves the `research` connector itself, like `brands`).
  The call records the run (`chat_research`) and a chat for it (`chat_chat` with `parent` set to the chat it
  researches for), starts that chat's Durable Object on the question, and returns "Started."
- A run **is a chat**: its own Durable Object, its own append-only log, the same turn runner, watchdog and tool
  rules as every chat. What differs (`research/core.py`): it may use only the sources and the web
  (`knowledge`, `web`), it is given its own prompt (`research/prompt.py`), its saved notes are not read, and it
  may make more source calls and rounds than a turn (`RESEARCH_SEARCHES`, `RESEARCH_ROUNDS`).
- It has a wall clock: `RESEARCH_SECONDS` (300). The watchdog alarm checks it; a run past it is cancelled and
  reports what it has.
- When its turn ends, the run posts its last words and the source lines the host wrote after them to the chat it
  is for (`ChatCore.research_done`), once: the event's ref is `research:<run>`, so a report delivered twice, or
  after a restart between posting and marking the run finished, adds nothing.
- No list of chats shows a run's chat and it cannot be opened (`chats_of` leaves out `parent != ''`). Deleting
  the chat erases its runs.

## Limits

One run at a time in a chat (`RESEARCH_BUSY`), `RESEARCHES_PER_DAY` (5) for a person (`RESEARCH_LIMIT`). A run's
model calls count against the person's daily allowance like any chat's.

## What a report may not do

Its words came from pages and sources, so they are data. The event says so, a card number in it is removed, it is
cut at 6,000 characters, and a turn that answers it is a turn that has read a source: nothing that changes
something (a payment, a transfer, an order, a note) runs until the person writes again (`turns/sources.py`).

A person's agent (PACT) needs no scope to search sources, read a page or start research: none of them touches the
person's account.

## Not built

Progress while a run works, a way to stop a run, and a run that continues an earlier one.
