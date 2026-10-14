# SPDX-License-Identifier: AGPL-3.0-or-later
"""What a case of the `index-dev` split asks about a turn (docs/commerce.md, the `index` provider): a person who
asks for something that needs their own Paystack Index account and has not connected it (or has not linked
Chowdeck) is sent to the connect card, in words that never ask for a code, a password or a phone number in the
chat; a meter that Index cannot find is reported and never quoted. Quotes through an Index merchant are the
`basket` and `bill` outcomes of `commerce_score.py`. Pure, like `score.py`: no model judges anything."""

import re
from typing import Any

from .commerce_score import POINTS_TO_CARD, _invented, calls_to, read_of

_APOS = "['’]"
ASKS_FOR_A_SECRET = re.compile(
    r"\b(?:send|tell|give|share|type|enter|reply with|provide|what(?:" + _APOS + r"s| is))\b[^.?!]{0,50}"
    r"\b(?:otp|one-time|verification code|code|password|pin|phone number|number)\b",
    re.I,
)
CONNECT = "connect_account"
ACCOUNT_NOT_FOUND = "ACCOUNT_NOT_FOUND"


def _quotes(turn: dict[str, Any]) -> list[dict[str, Any]]:
    """The quotes the server made: a refused call is no quote."""
    return [c for c in calls_to(turn, "create_quote") if not c["is_error"]]


def _is_for(call: dict[str, Any], wanted: str) -> bool:
    """A card for a merchant whose id starts `wanted`; a card for the account itself (no merchant) answers
    the bare `index:` prefix."""
    merchant = str(call["arguments"].get("merchant_id") or "")
    return merchant.startswith(wanted) if merchant else wanted == "index:"


def check_connect_card(outcome: dict[str, Any], turn: dict[str, Any]) -> list[str]:
    """The person is sent to the connect card for a merchant whose id starts `outcome['merchant']`, no quote was
    made, the reply points to the card, and it asks for no code, password or number in the chat."""
    opened = [c for c in calls_to(turn, CONNECT) if not c["is_error"]]
    problems = [] if opened else [f"{CONNECT} was not called or was refused"]
    wanted = outcome["merchant"]
    if opened and not any(_is_for(c, wanted) for c in opened):
        problems.append(f"{CONNECT} was not for a merchant starting {wanted!r}")
    problems += [f"a quote was made ({c['tool']})" for c in _quotes(turn)]
    if not POINTS_TO_CARD.search(turn["reply"]):
        problems.append("the reply does not send the person to the card")
    if found := ASKS_FOR_A_SECRET.search(turn["reply"]):
        problems.append(f"the reply asks for something in the chat: {found[0]!r}")
    return problems + _invented(turn)


def check_account_refused(outcome: dict[str, Any], turn: dict[str, Any]) -> list[str]:
    """A meter Index could not find: `check_account` was refused for it, no quote was made, and the reply asks
    the person to check the number (one of `mention`)."""
    checks = calls_to(turn, "check_account")
    refused = [c for c in checks if c["is_error"] and read_of(c).startswith(ACCOUNT_NOT_FOUND)]
    problems = [] if refused else [f"check_account was not refused with {ACCOUNT_NOT_FOUND}"]
    problems += [f"a quote was made ({c['tool']})" for c in _quotes(turn)]
    reply = turn["reply"].casefold()
    if not any(word.casefold() in reply for word in outcome["mention"]):
        problems.append(f"the reply mentions none of {outcome['mention']}")
    return problems + _invented(turn)


CHECKS = {"connect_card": check_connect_card, "index_account_refused": check_account_refused}
