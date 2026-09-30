# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the model cannot choose: the bank a transfer goes to (named by the person, resolved by the connector's
table), the smallest amount of any quote, and, in the host, the bank code it is not shown."""

from tools.mutations.model import AIRTIME, SRC, TRANSFER, Mutation
from tools.mutations.model import host_mutation as host

NAMES = ["tests/test_bank_names.py"]
BANK_TOOLS = [*TRANSFER, "tests/test_connector_transfer_tools.py"]
KEYS = ["tests/test_hub_keys.py"]
FLOOR = ["tests/test_amount_floor.py"]

MUTATIONS: list[Mutation] = [
    Mutation(
        "a bank that is not on the list is refused, not guessed",
        f"{SRC}/paystack/bank_names.py",
        "    raise BankNotFound(text, _nearest(asked))",
        '    return _BY_CODE["057"]',
        NAMES + BANK_TOOLS,
    ),
    Mutation(
        "a name that fits several banks is refused, not picked",
        f"{SRC}/paystack/bank_names.py",
        "if len(exact) > 1 or len(_containing(asked)) > 1:",
        "if False:",
        NAMES + BANK_TOOLS,
    ),
    Mutation(
        "a spelling the table was given by hand is the bank it names",
        f"{SRC}/paystack/bank_names.py",
        "    if compact in _ALIASES:\n        return _BY_CODE[_ALIASES[compact]]",
        "    if False:\n        return _BY_CODE[_ALIASES[compact]]",
        NAMES,
    ),
    Mutation(
        "a bank code that contradicts the bank named is refused",
        f"{SRC}/flows/bank_choice.py",
        "if stated is not None and stated != chosen.code:",
        "if False:",
        BANK_TOOLS,
    ),
    Mutation(
        "a transfer with no bank at all is refused, not sent to a default",
        f"{SRC}/flows/bank_choice.py",
        "        if stated is None:\n            raise DomainError(",
        "        if False:\n            raise DomainError(",
        BANK_TOOLS,
    ),
    Mutation(
        "a code nobody lists is refused",
        f"{SRC}/flows/bank_choice.py",
        "if not (bank_of_code(code) or _NUMERIC_CODE.fullmatch(code)):",
        "if False:",
        BANK_TOOLS,
    ),
    Mutation(
        "the account is looked up at the bank the connector resolved",
        f"{SRC}/flows/transfer.py",
        "AccountLookup(account, chosen.code)",
        'AccountLookup(account, "057")',
        BANK_TOOLS,
    ),
    Mutation(
        "no quote is made below the smallest amount",
        f"{SRC}/amount_floor.py",
        "if amount_kobo < MINIMUM_KOBO:",
        "if False:",
        FLOOR,
    ),
    Mutation(
        "the smallest amount is fifty naira",
        f"{SRC}/amount_floor.py",
        "MINIMUM_KOBO: Kobo = 5_000",
        "MINIMUM_KOBO: Kobo = 1",
        FLOOR,
    ),
    Mutation(
        "every quote of every connector passes the floor where it is made",
        f"{SRC}/ledger.py",
        "        assert_above_floor(amount)\n",
        "",
        FLOOR,
    ),
    Mutation(
        "airtime below the floor is told so, before the whole-naira rule and before VTpass",
        f"{SRC}/flows/airtime.py",
        "    assert_above_floor(amount_kobo)\n",
        "",
        FLOOR + AIRTIME,
    ),
    host(
        "the model is not shown a property the connector hides from it",
        "turns/hub.py",
        "if spec.get(MODEL_HIDDEN)} | {KEY_FIELD}",
        "if False} | {KEY_FIELD}",
        KEYS,
    ),
    host(
        "a property the connector requires of the model is required in its schema",
        "turns/hub.py",
        '*tool["inputSchema"].get(MODEL_REQUIRED, [])]',
        "]",
        KEYS,
    ),
]
