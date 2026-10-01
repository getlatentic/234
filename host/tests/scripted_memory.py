# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the scripted model does about memory, for a stack that has no key: it reads the notes message the
host puts after the system prompt, and calls the memory tools and the transfer tool the way a model that
follows the prompt would. Used by fake_model.py.

"remember my usual airtime is MTN 500" proposes a preference; "remember that I live in <place>" a fact;
"save <nickname> <10 digits> <bank>" a recipient; "forget <title>" forgets the note with that title;
"recall <words>" searches; "send <amount>k to <nickname>" quotes a transfer to the saved recipient by its id;
"remember my card number is <digits>" proposes it as a fact, as a careless model would, so the connector's
refusal is what stops it."""

import re

LABEL = "What this person asked 234 to remember."
LINE = re.compile(r"^- \[(?P<title>.+?)\]\((?P<id>[0-9a-f]{16})\) — (?P<hook>.*)$", re.M)
USUAL = re.compile(
    r"^remember my usual airtime is (?P<network>mtn|airtel|glo|9mobile) (?P<amount>\d+)$", re.I
)
LIVES = re.compile(r"^remember that i live in (?P<place>.+)$", re.I)
SAVE = re.compile(r"^save (?P<nick>\w+) (?P<account>\d{10}) (?P<bank>[a-z ]+)$", re.I)
CARD = re.compile(r"^remember my card number is (?P<digits>[\d ]+)$", re.I)
FORGET = re.compile(r"^forget (?P<title>.+)$", re.I)
RECALL = re.compile(r"^recall (?P<query>.+)$", re.I)
SEND = re.compile(r"^send (?P<amount>\d+)k to (?P<nick>\w+)$", re.I)
RENAME = re.compile(r"^rename (?P<title>.+?) to (?P<new>.+)$", re.I)


def notes_of(messages: list[dict]) -> dict[str, str]:
    """title (lower case) -> id, from the notes message, or nothing when there is none."""
    for message in messages[:3]:
        content = message["content"] if isinstance(message["content"], str) else ""
        if message["role"] == "user" and content.startswith(LABEL):
            return {m["title"].lower(): m["id"] for m in LINE.finditer(content)}
    return {}


def _tool(name: str, arguments: dict) -> dict:
    return {"tool": f"memory__{name}", "arguments": arguments}


def _from_the_person(text: str, notes: dict[str, str]) -> dict | None:
    if usual := USUAL.match(text):
        network, amount = usual["network"].upper(), usual["amount"]
        hook = f"{network}, {amount} naira"
        body = f"Buys {network} airtime of {amount} naira."
        return _tool("remember", {"kind": "preference", "title": "Usual airtime", "hook": hook, "body": body})
    if lives := LIVES.match(text):
        place = lives["place"].strip()
        return _tool(
            "remember", {"kind": "fact", "title": "Lives in", "hook": place, "body": f"Lives in {place}."}
        )
    if save := SAVE.match(text):
        arguments = {"kind": "recipient", "title": save["nick"].capitalize()}
        return _tool(
            "remember", {**arguments, "account_number": save["account"], "bank": save["bank"].strip()}
        )
    if card := CARD.match(text):
        digits = card["digits"].strip()
        return _tool("remember", {"kind": "fact", "title": "Card", "hook": "Card", "body": f"Card {digits}"})
    return _from_a_command(text, notes)


def _from_a_command(text: str, notes: dict[str, str]) -> dict | None:
    if recall := RECALL.match(text):
        return _tool("recall", {"query": recall["query"].strip()})
    if forget := FORGET.match(text):
        found = notes.get(forget["title"].strip().lower())
        return _tool("forget", {"id": found}) if found else {"text": "I have no note with that title."}
    if rename := RENAME.match(text):
        found = notes.get(rename["title"].strip().lower())
        return _tool("update", {"id": found, "title": rename["new"].strip()}) if found else None
    if send := SEND.match(text):
        found = notes.get(send["nick"].lower())
        if found is None:
            return {"text": "Send me their 10-digit account number and bank."}
        kobo = int(send["amount"]) * 100_000
        arguments = {
            "recipient_memory_id": found,
            "amount_kobo": kobo,
            "amount_as_user_said": f"{send['amount']}k",
        }
        return {"tool": "send-money__create_transfer_quote", "arguments": arguments}
    return None


def _after_a_tool(content: str) -> dict | None:
    if content.startswith("Proposed to"):
        return {"text": "Press Save on the card to keep it."}
    if content.startswith("Forgot"):
        return {"text": "Done, it is forgotten."}
    if content.startswith("Saved notes follow"):
        titles = re.findall(r'title: "([^"]+)"', content)
        return {"text": "I found: " + ", ".join(titles) + "." if titles else "I found nothing."}
    if content.startswith("MEMORY_REFUSED"):
        return {"text": "I can't keep that. " + content.split(": ", 1)[1].split(". ")[0] + "."}
    if content.startswith(("MEMORY_", "BANK_", "PROVIDER_ERROR", "RECIPIENT_")):
        return {"text": "That did not work: " + content.split(": ", 1)[1].split(". ")[0] + "."}
    return None


def answer(messages: list[dict], tools: list[dict]) -> dict | None:
    """The reply to a memory request, or None when the message is not one."""
    last = messages[-1]
    if last["role"] == "tool":
        return _after_a_tool(last["content"])
    if last["role"] != "user" or not isinstance(last["content"], str):
        return None
    reply = _from_the_person(last["content"].strip(), notes_of(messages))
    offered = {t["function"]["name"] for t in tools}
    if reply and "tool" in reply and reply["tool"] not in offered:
        return {"text": "I can't remember things for you unless you sign in."}
    return reply
