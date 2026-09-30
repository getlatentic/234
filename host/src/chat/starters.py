# SPDX-License-Identifier: AGPL-3.0-or-later
"""The suggestions on the empty home. A starter either sends its text (`send`: it works as a first message
with the connectors as they are) or puts it in the composer for the person to finish (`fill`: it lacks
something only the person knows, such as a phone number). `label` is what the button says and `text` what goes
in the field; the simulators and the scripted model answer every one of them once completed
(tests/test_starters.py, conformance/chat-home.mjs)."""

from typing import NamedTuple

MAX_LENGTH = 32


class Starter(NamedTuple):
    icon: str
    label: str
    text: str
    sends: bool


def send(icon: str, message: str) -> Starter:
    return Starter(icon, message, message, True)


def fill(icon: str, label: str, beginning: str) -> Starter:
    return Starter(icon, label, beginning, False)


STARTERS = (
    fill("airtime", "Buy ₦500 MTN airtime", "Buy ₦500 MTN airtime for "),
    fill("data", "Buy ₦1,000 MTN data", "Buy ₦1,000 MTN data for "),
    fill("transfer", "Send ₦5,000 to a friend", "Send ₦5,000 to "),
    send("food", "Order jollof rice for delivery"),
    send("pay", "Pay ₦2,500 to Ada Stores"),
    send("help", "What can you do?"),
)
