# SPDX-License-Identifier: AGPL-3.0-or-later
"""What a mutation is, and the groups of tests the mutation files name."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Mutation:
    guardrail: str
    file: str
    find: str
    replace: str
    tests: list[str]
    project: str = "checkout"


LEDGER = ["tests/test_ledger.py", "tests/test_ledger_races.py"]
PAYMENT = ["tests/test_flow_payment.py"]
AIRTIME = ["tests/test_flow_airtime.py", "tests/test_flow_airtime_races.py"]
TRANSFER = ["tests/test_flow_transfer.py"]
FOOD = ["tests/test_flow_food.py"]
CONNECTOR_TOOLS = [
    "tests/test_connectors.py",
    "tests/test_connector_payment_tools.py",
    "tests/test_connector_transfer_tools.py",
    "tests/test_connector_airtime_food_tools.py",
]
CONFIG = ["tests/test_config.py", "tests/test_app_wiring.py"]
MENU_CARD = ["tests/test_menu_card_tools.py", "tests/test_menu_view.py", "tests/test_food_menu.py"]

HOST = "host"
HOST_SRC = "src"

SRC = "src/checkout"


def host_mutation(guardrail: str, file: str, find: str, replace: str, tests: list[str]) -> Mutation:
    """A guardrail of the Django host, `file` being relative to the host's `src`."""
    return Mutation(guardrail, f"{HOST_SRC}/{file}", find, replace, tests, HOST)
