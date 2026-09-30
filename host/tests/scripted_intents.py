# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the scripted model does with the suggestions on the empty home and with what follows them.

It is a stand-in for a model that follows the host's prompt and the schemas it is offered (which have no
idempotency key: the host supplies it): it asks for the one thing a request lacks,
calls the connector's tool when it has everything, says what it can do from the tools it was offered (not
from a fixed sentence), and turns down anything else with the same list. Used by fake_model.py.

It can also play the model that does not follow the prompt, so the page's handling of a refused call is
testable: "blank phone: <airtime request>" calls the airtime tool with an empty number, which the connector
refuses, and then asks for the number (or, when the request names one, calls the tool again with it);
"blank phone, silent: <airtime request>" says nothing after the refusal."""

import re
from typing import Any

AMOUNT = r"[₦N]?\s?(?P<amount>[\d,]+)"
NETWORKS = r"(?P<network>mtn|airtel|glo|9mobile)"
NUMBER = r"(?:\s+for\s+(?P<phone>(?:\+?234|0)\d{10}))?"
AIRTIME_ASK = re.compile(rf"^buy\s+{AMOUNT}\s+{NETWORKS}\s+airtime{NUMBER}$", re.I)
DATA_ASK = re.compile(rf"^buy\s+{AMOUNT}\s+{NETWORKS}\s+data{NUMBER}$", re.I)
TRANSFER_ASK = re.compile(rf"^send\s+{AMOUNT}\s+to\s+(?:a|my)\s+\w+$", re.I)
TRANSFER_TO = re.compile(rf"^send\s+{AMOUNT}\s+to\s+(?P<account>\d{{10}})\s+(?P<bank>[a-z ]+)$", re.I)
FOOD_ASK = re.compile(r"^order\s+(?P<what>.+?)\s+for delivery$", re.I)
BLANK_PHONE = re.compile(r"^blank phone(?P<silent>, silent)?: (?P<ask>.+)$", re.I)
REFUSED = "Invalid arguments for"
CAN_DO = re.compile(r"\bwhat can you do\b", re.I)
PHONE = re.compile(r"^(?P<phone>(?:\+?234|0)\d{10})$")
ACCOUNT = re.compile(r"^(?P<account>\d{10})\s+(?P<bank>[a-z ]+)$", re.I)
PLAN = re.compile(r"^(?P<code>[\w-]+): .*, ₦(?P<price>[\d,]+)", re.M)
CAPABILITY_OF_TOOL = {
    "create_airtime_quote": "buy airtime",
    "create_data_quote": "buy data",
    "create_transfer_quote": "send money to a bank account",
    "search_menu": "order food",
    "create_payment_quote": "pay a merchant",
}


def capabilities(tools: list[dict[str, Any]]) -> str:
    """What the offered tools let it do, as a phrase: 'buy airtime, send money and pay a merchant'."""
    names = {t["function"]["name"].split("__")[-1] for t in tools}
    phrases = [phrase for tool, phrase in CAPABILITY_OF_TOOL.items() if tool in names]
    return ", ".join(phrases[:-1]) + f" and {phrases[-1]}" if len(phrases) > 1 else "".join(phrases)


def refusal(tools: list[dict[str, Any]]) -> str:
    can = capabilities(tools)
    return f"I can't do that. I can {can}." if can else "I can't do that."


def _naira(text: str) -> int:
    return int(re.sub(r"\D", "", text))


def _earlier(messages: list[dict], pattern: re.Pattern) -> re.Match | None:
    for message in reversed(messages):
        if message["role"] == "user" and isinstance(message["content"], str):
            found = pattern.search(message["content"].strip())
            if found:
                return found
    return None


def _airtime_quote(ask: re.Match, phone: str, said: str) -> dict:
    return {
        "tool": "airtime__create_airtime_quote",
        "arguments": {
            "network": ask["network"].lower(),
            "phone": phone,
            "amount_kobo": _naira(ask["amount"]) * 100,
            "amount_as_user_said": said,
        },
    }


def _after_a_number(messages: list[dict], phone: str) -> dict | None:
    if ask := _earlier(messages, AIRTIME_ASK):
        return _airtime_quote(ask, phone, f"₦{_naira(ask['amount'])}")
    if ask := _earlier(messages, DATA_ASK):
        return {"tool": "airtime__list_data_plans", "arguments": {"network": ask["network"].lower()}}
    return None


def _transfer_quote(amount: str, account: str, bank: str) -> dict:
    return {
        "tool": "send-money__create_transfer_quote",
        "arguments": {
            "account_number": account,
            "bank": bank.strip(),
            "amount_kobo": _naira(amount) * 100,
            "amount_as_user_said": f"₦{_naira(amount)}",
        },
    }


def _after_an_account(messages: list[dict], account: re.Match) -> dict | None:
    ask = _earlier(messages, TRANSFER_ASK)
    return _transfer_quote(ask["amount"], account["account"], account["bank"]) if ask else None


def _blank_request(text: str) -> tuple[re.Match, str | None, bool] | None:
    """(the airtime request, the number it names if any, whether to stay silent after a refusal)."""
    blank = BLANK_PHONE.match(text.strip())
    ask = AIRTIME_ASK.match(blank["ask"]) if blank else None
    return (ask, ask["phone"], bool(blank["silent"])) if ask else None


def _blank_phone(text: str) -> dict | None:
    """The airtime tool called the way a model that skipped the question would call it."""
    request = _blank_request(text)
    return _airtime_quote(request[0], "", f"₦{_naira(request[0]['amount'])}") if request else None


def _after_a_refusal(messages: list[dict]) -> dict | None:
    """What the model that called with a blank number does once the connector has refused the call."""
    texts = [m["content"] for m in messages if m["role"] == "user" and isinstance(m["content"], str)]
    request = next((r for r in map(_blank_request, reversed(texts)) if r), None)
    if request is None:
        return None
    ask, phone, silent = request
    if silent:
        return {"text": ""}
    if phone:
        return _airtime_quote(ask, phone, f"₦{_naira(ask['amount'])}")
    return {
        "text": f"Which number should get the ₦{_naira(ask['amount']):,} {ask['network'].upper()} airtime?"
    }


def _from_the_person(text: str, messages: list[dict], tools: list[dict]) -> dict | None:
    if blank := _blank_phone(text):
        return blank
    if CAN_DO.search(text):
        return {"text": f"I can {capabilities(tools)}. You approve every payment on a card."}
    if ask := AIRTIME_ASK.match(text) or DATA_ASK.match(text):
        if ask["phone"]:
            return _after_a_number([{"role": "user", "content": text}], ask["phone"])
        kind = "airtime" if AIRTIME_ASK.match(text) else "data"
        return {
            "text": f"Which number should get the ₦{_naira(ask['amount']):,} {ask['network'].upper()} {kind}?"
        }
    if TRANSFER_ASK.match(text):
        return {"text": "Send me their 10-digit account number and bank."}
    if food := FOOD_ASK.match(text):
        return {"tool": "food-order__search_menu", "arguments": {"query": food["what"]}}
    if phone := PHONE.match(text):
        return _after_a_number(messages, phone["phone"])
    if direct := TRANSFER_TO.match(text):
        return _transfer_quote(direct["amount"], direct["account"], direct["bank"])
    if account := ACCOUNT.match(text):
        return _after_an_account(messages, account)
    return None


def _data_quote(messages: list[dict], plans: str) -> dict | None:
    ask = _earlier(messages, DATA_ASK)
    named = _earlier(messages, PHONE)
    phone = ask["phone"] or (named["phone"] if named else None) if ask else None
    if ask is None or phone is None:
        return None
    wanted = _naira(ask["amount"])
    plan = next((p for p in PLAN.finditer(plans) if _naira(p["price"]) == wanted), None)
    if plan is None:
        return {"text": f"There is no {ask['network'].upper()} data plan for ₦{wanted:,}."}
    return {
        "tool": "airtime__create_data_quote",
        "arguments": {
            "network": ask["network"].lower(),
            "phone": phone,
            "plan_code": plan["code"],
        },
    }


def answer(messages: list[dict], tools: list[dict]) -> dict | None:
    """The reply to a starter or what follows it, or None when the message is neither."""
    last = messages[-1]
    if last["role"] == "tool" and last["content"].startswith(REFUSED):
        return _after_a_refusal(messages)
    if last["role"] == "tool" and "data plans:" in last["content"]:
        return _data_quote(messages, last["content"])
    if last["role"] != "user" or not isinstance(last["content"], str):
        return None
    return _from_the_person(last["content"].strip(), messages, tools)
