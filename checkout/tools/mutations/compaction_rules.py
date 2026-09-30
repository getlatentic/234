# SPDX-License-Identifier: AGPL-3.0-or-later
"""The guardrails of the host's context compaction: where the conversation may be cut, what the summariser is
shown, what a summary must keep, and what a failed or repeated compaction may not do. Each runs against the
host's own tests."""

from tools.mutations.model import Mutation
from tools.mutations.model import host_mutation as host

PLAN = ["tests/test_plan.py", "tests/test_compaction.py"]
UNITS = ["tests/test_plan.py", "tests/test_messages.py", "tests/test_compaction.py"]
FACTS = ["tests/test_facts.py", "tests/test_compaction.py"]
SCRUB = ["tests/test_scrub.py", "tests/test_transcript.py", "tests/test_compaction.py"]
COMPACTOR = ["tests/test_compaction.py", "tests/test_runner_compaction.py", "tests/test_chat_compact.py"]
MODEL = ["tests/test_model.py", "tests/test_compaction.py", "tests/test_runner_compaction.py"]

MUTATIONS: list[Mutation] = [
    host(
        "compaction: a cut falls only where every message before it has lower seqs than every one after it",
        "turns/compaction/plan.py",
        "        if prefix_last < suffix_first[index]:",
        "        if True:",
        PLAN,
    ),
    host(
        (
            "compaction: a reply and the results of its calls are cut together "
            "(its last seq is its last result's)"
        ),
        "turns/messages.py",
        "            last = max(last, result.seq)",
        "            last = event.seq",
        UNITS,
    ),
    host(
        "compaction: a call with no result yet pins its reply and everything after it",
        "turns/messages.py",
        "            last, text = NEVER, NO_RESULT",
        "            last, text = event.seq, NO_RESULT",
        UNITS,
    ),
    host(
        "compaction: the flow of the latest open quote is kept word for word",
        "turns/compaction/plan.py",
        "        and (floor is None or seq <= floor)",
        "        and True",
        PLAN,
    ),
    host(
        "compaction: a quote waiting on the person or the payment is open",
        "turns/compaction/quotes.py",
        "        if self.phase not in OPEN_PHASES:",
        "        if False:",
        [*PLAN, "tests/test_quotes.py"],
    ),
    host(
        "compaction: at least the recent tokens asked for are kept word for word",
        "turns/compaction/plan.py",
        "        if tokens[i] >= keep_recent_tokens",
        "        if True",
        PLAN,
    ),
    host(
        "compaction: the model reads only the messages after the cut",
        "turns/messages.py",
        "if u.first >= cut]",
        "if True]",
        UNITS,
    ),
    host(
        "compaction: links are taken out of what the summariser is shown and of the summary",
        "turns/compaction/scrub.py",
        "    text = _LINK.sub(LINK_REMOVED, text)",
        "    text = text",
        SCRUB,
    ),
    host(
        "compaction: tokens and long secrets are taken out of what the summariser is shown",
        "turns/compaction/scrub.py",
        "for pattern in (_API_KEY, _LABELLED, _BEARER, _ONE_TIME_CODE, _LONG_SECRET):",
        "for pattern in (_API_KEY, _LABELLED, _BEARER, _ONE_TIME_CODE):",
        SCRUB,
    ),
    host(
        "compaction: card numbers are taken out of what the summariser is shown",
        "turns/compaction/scrub.py",
        "    return redact_card_numbers(text, CARD_REMOVED)",
        "    return text",
        SCRUB,
    ),
    host(
        "compaction: the arguments of a tool call are scrubbed before the summariser reads them",
        "turns/compaction/transcript.py",
        '    return scrubbed(call["arguments"] or "{}")[:ARGUMENT_CHARS]',
        '    return (call["arguments"] or "{}")[:ARGUMENT_CHARS]',
        SCRUB,
    ),
    host(
        "compaction: a card is written for the summariser from the quote's own facts, "
        "never its token or link",
        "turns/compaction/transcript.py",
        "    return scrubbed(line.strip())",
        "    return line.strip() + ' ' + str(event.payload)",
        SCRUB,
    ),
    host(
        "compaction: no tool result text reaches the summariser",
        "turns/compaction/transcript.py",
        "    return f\"[Tool result]: {'refused' if event.payload.get('is_error') else 'ok'}\"",
        "    return f\"[Tool result]: {event.payload['result_text']}\"",
        SCRUB,
    ),
    host(
        "compaction: the summary is scrubbed before it is stored",
        "turns/compaction/summary.py",
        "    return scrubbed(_usable(text, reason))",
        "    return _usable(text, reason)",
        SCRUB,
    ),
    host(
        "compaction: a summary is checked for every amount, number and open quote of what it covers",
        "turns/compaction/summary.py",
        '    if not missing:\n        return Summary(text, "model", 1)',
        '    if True:\n        return Summary(text, "model", 1)',
        FACTS,
    ),
    host(
        "compaction: a fact the summary lacks and the kept messages lack is reported missing",
        "turns/compaction/facts.py",
        "    return required - said - kept_verbatim",
        "    return Facts()",
        FACTS,
    ),
    host(
        "compaction: a summary that missed facts is asked for again with the missing facts listed",
        "turns/compaction/summary.py",
        "        retried = await _ask(model, without_block(previous), transcript, missing, timeout)",
        "        retried = text",
        FACTS,
    ),
    host(
        "compaction: a summary that still misses facts is completed with the facts written by rule",
        "turns/compaction/summary.py",
        '    return Summary(f"{retried}\\n\\n{facts_block(events, last, now_ms)}", "block", 2)',
        '    return Summary(retried, "block", 2)',
        FACTS,
    ),
    host(
        "compaction: a summary that cannot be had falls back to trimming, whatever went wrong",
        "turns/compaction/compactor.py",
        "        except Exception as failed:",
        "        except SummaryFailed as failed:",
        COMPACTOR,
    ),
    host(
        "compaction: a failed summary is followed by the fallback, not by a failed turn",
        "turns/compaction/compactor.py",
        "            return await self._trimmed(events, reason, keep, system, tools, started)",
        "            raise",
        COMPACTOR,
    ),
    host(
        "compaction: a compactor that raises never fails the turn's round",
        "turns/runner.py",
        "        except Exception:\n            logger.exception",
        "        except ZeroDivisionError:\n            logger.exception",
        COMPACTOR,
    ),
    host(
        "compaction: a compaction's identity is the range it covers, so each range is written once",
        "turns/compaction/compactor.py",
        '    return f"compaction:{first}-{last}:{pruned_before}"',
        '    return "compaction"',
        COMPACTOR,
    ),
    host(
        "compaction: no second compaction with the same identity is appended",
        "turns/eventlog.py",
        '            f"AND NOT EXISTS (SELECT 1 FROM {TABLE} WHERE chat_id = ?1 AND type = ?2 '
        'AND ref = ?3) "',
        '            f"AND 1 = 1 "',
        COMPACTOR,
    ),
    host(
        "compaction: a compaction is appended only while the newest one is the one it was decided against",
        "turns/eventlog.py",
        'AND type = ?2) = ?6 "',
        'AND type = ?2) = ?6 OR 1 = 1 "',
        COMPACTOR,
    ),
    host(
        "compaction: manual requests that arrive together make one compaction",
        "turns/compaction/compactor.py",
        "            if (newest := await self._log.newest_of_type(kinds.COMPACTION)) != seen:",
        "            if (newest := await self._log.newest_of_type(kinds.COMPACTION)) == -1:",
        COMPACTOR,
    ),
    host(
        "compaction: a summary call is a model call against the daily caps",
        "turns/compaction/compactor.py",
        "        if not await self._permit():",
        "        if False:",
        COMPACTOR,
    ),
    host(
        "compaction: nothing is compacted while the context is under the threshold",
        "turns/compaction/compactor.py",
        "        if self._used(events, system, tools) <= self._settings.compact_threshold_tokens:\n"
        "            return False\n"
        "        async with self._lock:\n"
        "            events = await self._log.context()\n"
        "            if self._used(events, system, tools) <= self._settings.compact_threshold_tokens:\n"
        "                return False\n",
        "        async with self._lock:\n            events = await self._log.context()\n",
        COMPACTOR,
    ),
    host(
        "compaction: a chat being deleted is not compacted",
        "turns/compaction/compactor.py",
        "        if self._closed:\n            return None",
        "        if False:\n            return None",
        COMPACTOR,
    ),
    host(
        "compaction: a summary is never asked of a Claude model",
        "turns/settings.py",
        '        if any(word in self.llm_model.lower() for word in ("claude", "anthropic")):',
        "        if False:",
        MODEL,
    ),
    host(
        "compaction: a refusal because the context did not fit is told from any other",
        "turns/model.py",
        "    too_long = status in (None, 400, 413) and CONTEXT_REFUSAL.search(body[:4000])",
        "    too_long = False",
        MODEL,
    ),
    host(
        "compaction: an error event in a stream that began with 200 is an error, not an empty reply",
        "turns/model.py",
        '                    if isinstance(chunk.get("error"), dict):',
        "                    if False:",
        MODEL,
    ),
    host(
        "compaction: a context the endpoint refused as too long is trimmed and asked again once",
        "turns/runner.py",
        "            except ContextTooLong:",
        "            except ZeroDivisionError:",
        MODEL,
    ),
    host(
        "a model round has a deadline, so a stream that never finishes ends the turn",
        "turns/runner.py",
        "        except TimeoutError as error:\n            raise ModelError(TOO_SLOW) from error",
        "        except ZeroDivisionError as error:\n            raise ModelError(TOO_SLOW) from error",
        ["tests/test_runner.py"],
    ),
    host(
        "compaction: only the owner of a chat compacts it",
        "chat/views/compact.py",
        "    if chat.owner != request.owner:",
        "    if False:",
        COMPACTOR,
    ),
    host(
        "compaction: the provider's count of the last request corrects the next estimate",
        "turns/tokens.py",
        '            return min(MOST_RATIO, max(LEAST_RATIO, usage["prompt_tokens"] / payload["estimate"]))',
        "            return 1.0",
        ["tests/test_tokens.py", "tests/test_compaction.py", "tests/test_runner_compaction.py"],
    ),
]
