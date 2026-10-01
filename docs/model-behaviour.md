# What the real model does with a request that lacks something

Measured 2026-09-30 with `openai.gpt-oss-120b` on Bedrock, through the host, by `tools/real-model.sh probe` (`host/tests/real_probe.py`). The key stays in the environment of that one command and is never printed.

## The defect

On the live site a visitor pressed "Buy ₦500 MTN airtime", which has no number. The model called `create_airtime_quote` with `phone: ""`, the connector refused it ("Invalid arguments for create_airtime_quote: phone: String should have at least 10 characters"), the model then asked for the number, and the page showed the refusal as a red row with raw JSON.

It is the model's choice, not a rare accident: with the prompt as it was (`a39da78`), **19 of 40** draws of that one starter called the tool with an empty number (a first pass of 5 draws saw none, so a small pass proves little). The prompt told it to "ask only for what is missing", and the tool's schema requires the number, which it filled with `""`.

## What the prompt says now

`host/src/turns/prompt.py` builds it from the connectors that are on, 1,914 characters with all four. Phase 2 of [../evaluation/RESULTS.md](../evaluation/RESULTS.md) added a list of bank codes, a bills sentence and an injection sentence; phase 3 took the bank codes and the bills sentence out (the connector resolves the bank by name, and naming bills made the model quote one) and added one rule: a message with two different amounts, or one that contradicts itself, is asked about, never decided silently. Each connector has two entries: what it does and what a request needs. A connector that is off is neither offered nor described (`tests/test_prompt.py`). In short:

- what a request needs before its tool is called (airtime or data: network, amount and phone number; a transfer: amount, account number and bank, the bank passed by name as the person said it, never a code; a payment: merchant and amount; food: only a dish, then `search_menu`, because the menu card takes the order);
- if the person has not given the phone number, ask for it and call no airtime or data tool until it is there; for data, then list the plans and pick the one that costs the amount;
- if anything is missing, call no tool and ask for that one thing in one short question;
- never guess, invent, leave empty or use a placeholder for a number, account, amount, merchant, item or area;
- nothing about idempotency keys: the model is not offered one (see "Idempotency keys" below).

A person who is not signed in has no "saved recipient" (no tool stores one for them), so their prompt does not mention one. A signed-in person's prompt gains one paragraph about their saved notes and the transfer tool takes a saved recipient by id: [memory.md](memory.md).

What the iterations taught (each was a probe run, not a guess):

| Wording tried | Effect |
|---|---|
| "food is ordered on the menu card, so search the menu" | 3 of 5 searched; the others asked for an area, or said nothing |
| "food needs only a dish: call search_menu with it straight away" | 5 of 5 searched; one draw then called `create_food_quote` with item `item1` in area `Yaba`: a guessed item. "never quote food yourself" and "item or area" in the never-list removed it (40 of 40) |
| "not the reason" for a payment | the model sent `description: ""`; naming the default ("Payment") fixed it |
| "call no tool, not even to look something up" | 2 of 40 data draws still called `create_data_quote` with `phone: ""` after listing plans |
| "ask for the phone number first, plan list included" | 1 of 60 still wrong, but a complete request ("for 07031234567") was now asked for the number again: 2 of 20 quoted (the old prompt: 17 of 20) |
| "if the phone number is not in their words, ask for it and call no airtime or data tool until you have it" | 60 of 60 asked, 0 wrong; the complete data request quoted 60 of 60 |
| key rule with no example | the model wrote `a1b2c3d4e5f6g7h8i9j0` (or its capitals) in 74 of 79 keys; the negative example "a pattern such as a1b2c3" brought it to a few repeats. Superseded: the host now makes the key and the prompt has no rule |

## Results

A draw is one new visitor and chat sending the prompt once. `finish_reason` is recorded for every round. **Wrong** is a quote call that the person's words do not support: an empty or different number, account, merchant or amount, the wrong tool, or a call the connector refused as invalid. **Asked** is a reply that asks and calls no quote tool. **Right** is, for the first three prompts, asking without calling; for the others, the right quote (or, for food, `search_menu` with the dish) with the right arguments and no refusal.

Before, the prompt as it was, 5 draws each (the last row 20):

| Prompt | Draws | Wrong | Asked | Right |
|---|---|---|---|---|
| Buy ₦500 MTN airtime | 5 (and 40) | 0 (and **19**) | 5 (and 21) | 5 (and 21) |
| Buy ₦1,000 MTN data | 5 | 0 | 5 | 5 |
| Send ₦5,000 to a friend | 5 | 0 | 5 | 5 |
| Order jollof rice for delivery | 5 | 0 | 5 (after the menu card) | 5 |
| Pay ₦2,500 to Ada Stores | 5 | 1 (a key with a space, refused) | 1 | 4 |
| Buy 500 naira MTN airtime for 07031234567 | 5 | 0 | 0 | 5 |
| Send 5k to Ada Okafor, GTBank 0123456789 | 5 | 0 | 0 | 5 |
| Buy ₦1,000 MTN data for 07031234567 | 20 | 1 | 3 | 17 |

Idempotency keys that contain a date (`user-20230930-001`, `pay-ada-20230930-001`): 9 of 15 in that pass, 9 of 19 in the airtime run, 8 of 20 in the complete data request.

After, the shipped prompt, 5 draws each (`PROBE_LOG` kept the draws):

| Prompt | Draws | Wrong | Asked | Right |
|---|---|---|---|---|
| Buy ₦500 MTN airtime | 5 | 0 | 5 | 5 |
| Buy ₦1,000 MTN data | 5 | 0 | 5 | 5 |
| Send ₦5,000 to a friend | 5 | 0 | 5 | 5 |
| Order jollof rice for delivery | 5 | 0 | 1 (after the menu card) | 5 |
| Pay ₦2,500 to Ada Stores | 5 | 0 | 0 | 5 |
| Buy 500 naira MTN airtime for 07031234567 | 5 | 0 | 0 | 5 |
| Buy ₦1,000 MTN data for 07031234567 | 5 | 0 | 0 | 5 |
| Send 5k to Ada Okafor, GTBank 0123456789 | 5 | 0 | 0 | 5 |

Finish reasons of the 73 rounds: 40 `stop`, 33 `tool_calls`; every turn ended `completed` (20) or `input_required` (20, a card is waiting). No `length`, no `error`, no ceiling on output.

The same again with 20 draws each (160 turns): **0 wrong**, every draw right; 128 `tool_calls` rounds, 160 `stop`. The airtime starter alone, 40 draws: 0 wrong, 40 asked (before: 19 wrong of 40). The data starter without a number, 60 draws on the wording just before the final one: 0 wrong, 60 asked. Dated keys: 0 in all of these.

An earlier 20-draw pass of this prompt family had one draw end `failed` with `finish_reason: error` (an upstream failure, no tool call; the probe did not yet record notices) and one food draw that ended with no words and no call. The final passes had neither, which is not proof that they no longer happen.

## Idempotency keys

**The defect.** The model used to supply `idempotency_key` for every quote tool, and the prompt could not make the keys unique: with the wording above it still wrote the same few strings across chats (`A1b2C3d4E5f6G7h8I9j0` in 5 of the 81 keys of the 20-draw pass, 76 distinct). The connectors' ledger keeps an owner's keys apart from others' and refuses the same key with a different request (`IDEMPOTENCY_CONFLICT`), but the same key with the same request replays the first quote by design. So a person who buys the same ₦500 MTN airtime for the same number on two days could be handed the old quote (perhaps one already delivered); with another request under a reused key they would get a refusal they cannot understand.

**The fix.** The model does not manage keys. The host derives one for every model-originated call of a tool that has an `idempotency_key` parameter, from the owner, the chat id and the model's own id for that call (`turns/idempotency.py`, [durable-chat.md](durable-chat.md#retries-and-the-idempotency-key)):

- The schema the host offers the model has no `idempotency_key`, neither in `properties` nor in `required` (`Hub.model_tools`). The connectors' own schemas are unchanged: the card and other clients still use them.
- At call time the hub puts the derived key into the arguments, over any value the model still sends.
- The prompt has no sentence about keys.
- A card's own calls (`order_from_menu` keys itself from `card_id`) and A2A callers are not touched.

A retried call (a turn resumed after a restart reads the same call id from the log) has the same key, so the ledger returns the quote it already made. Any other request, in this chat or another, has a new call id and so a new key and a new quote.

**Two identical calls in one reply.** A key per call would make two quotes, the second an exact copy of the first. The runner instead makes the first and answers the second, without calling the connector, with the first's result behind a line that says it was not made again; no second card is recorded. Why that is right for the person:

- Two identical quote calls in one reply are far more likely a model slip than two purchases. The costs are not symmetrical: a second quote is a second card that looks like the first, and approving both buys twice; a held-back call costs the model one sentence, and if the person did want two, the model can call again in its next reply, which is a new request with a new key and a new quote (the real model did this on "Buy the same again").
- The alternative that the derived key alone would give, two fresh quotes, is what the person is least able to sort out. Reusing one key for both calls would have replayed the first quote, but hides that a second call was made and breaks the rule that a key names one call.
- The scope is narrow on purpose: only tools that take a key (they make quotes), the same tool and the same arguments (a key the model still sends is ignored in the comparison), and only inside one reply. The same request in a later reply is a new request. Reads (`list_data_plans`, `search_menu`, `get_quote_status`) are run every time.

`tests/test_runner_keys.py` (scripted model and a ledger double) and `tests/test_worker_keys.py` (real connectors on local workerd: `twice: airtime ...` makes one card, the second tool result is the first's behind the line, and asking again afterwards makes a second quote) pin this. The real model was never seen to do it: no draw below held back a call, so this path is exercised by the scripted model only.

**Nothing regressed with the real model** (`openai.gpt-oss-120b`, through `tools/real-model.sh probe`, 2026-09-30; `PROBE_LOG` kept the draws). Wrong, asked, right and finish reasons are counted as above. `cards` is the number of cards the chats got, `off` the draws whose number of cards is not what the prompt calls for (none for an ask, one otherwise, two for the "again" prompt), `keys` the calls in which the model sent a key although it is not offered one, `repeats` the calls held back as a repeat.

| Pass | Draws | Wrong | Right | Cards off | Keys the model sent | Repeats |
|---|---|---|---|---|---|---|
| the eight prompts above, 3 draws each | 24 | 0 | 24 | 0 | 0 | 0 |
| the same and "Buy ₦500 MTN airtime for 07031234567" then "Buy the same again" (9 prompts), 5 draws each | 45 | 0 | 44 | 1 | 0 | 0 |
| the "again" prompt alone, 10 draws | 10 | 0 | 10 | 0 | 0 | 0 |

The "again" prompt in all 15 draws: 14 made a second quote in the same chat (in the 10-draw pass the two quote ids differed every time, both for the same number and amount); in one the model answered that the request was ready and made no second call, which is the model's choice and not a wrong quote.

Across the three passes (79 draws, 176 rounds): 94 `stop`, 82 `tool_calls`; the last turn of every draw ended `completed` (33) or `input_required` (46). No `length`, no `error`, and no draw where the model sent a key or made a call the connector refused.

## What is not measured

One model, one endpoint, one afternoon; five draws cannot see a one-in-fifty event (the first pass of the old prompt saw none of a one-in-two one). English only, single turns: the person's answer to the question (a number typed next) is run in the page with a real model by `conformance/real-starters.mjs` (airtime, data and transfer each quoted on the first try), not drawn repeatedly. Yoruba and Pidgin were not tried. A model that asks "Which bank code should I use for GTBank?" (3 of 20 in one pass) is asking, not guessing, and is counted as asked.

## Held-out evaluation

[../evaluation/RESULTS.md](../evaluation/RESULTS.md): 77 cases authored before the run, 3 draws each, scored without a model. Phase 1 (prompt untouched): 87% of draws pass, no approve by the model, two draws quoted an injected 1 kobo. Phase 3 (after the connector resolved bank names, refused amounts under ₦50 and the prompt lost its bank codes and bills sentence; not held-out): 90% pass, no dangerous failure in 231 draws, and in 20 more draws of each of the two cases that had failed that way, none. The eight prompts above are the `tuning` split there.

## Run it

`PORT_BASE=8920 tools/real-model.sh probe 5` with `LLM_BASE_URL` (the endpoint without `/chat/completions`), `LLM_MODEL=openai.gpt-oss-120b` and `LLM_API_KEY` in the environment; `probe 40 "MTN airtime"` draws only the prompts that contain those words; `PROBE_LOG=file.jsonl` keeps every draw. The probe now also runs a prompt with a second message in the same chat ("Buy the same again") and counts the quote cards, the calls held back as a repeat and the keys the model sent. `tools/down.sh` stops the stack and removes the key file. `conformance/real-starters.mjs` runs the starters in the page against the same stack.
