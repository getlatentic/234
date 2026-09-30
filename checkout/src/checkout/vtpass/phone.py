# SPDX-License-Identifier: AGPL-3.0-or-later
import re

from ..errors import DomainError

# Numbers the VTpass sandbox documents as scenarios: 08011111111 succeeds, 201000000000 is pending,
# 500000000000 answers unexpectedly, 400000000000 does not answer, 300000000000 times out.
SANDBOX_SCENARIO_NUMBERS = frozenset({"201000000000", "500000000000", "400000000000", "300000000000"})
# The sandbox fails "any other number", so it has no number that means failure. The simulator needs one
# to keep the failed-delivery path demonstrable; the sandbox fails this number like any other.
SIMULATED_FAILURE_NUMBER = "100000000000"
DOCUMENTED_SUCCESS_NUMBER = "08011111111"

_NIGERIAN_MOBILE = re.compile(r"^0[789][01]\d{8}$")
_SEPARATORS = re.compile(r"[\s()-]")
_COUNTRY_CODE = re.compile(r"^(?:\+234|234)(?=\d{10}$)")


def is_nigerian_mobile(number: str) -> bool:
    """A mobile number in national form: 11 digits, 0, then 7, 8 or 9, then 0 or 1."""
    return _NIGERIAN_MOBILE.fullmatch(number) is not None


def normalise_phone(text: str) -> str:
    """A Nigerian mobile number as 0803..., or a VTpass scenario number. Anything else is refused."""
    local = _COUNTRY_CODE.sub("0", _SEPARATORS.sub("", text))
    if is_nigerian_mobile(local) or local in SANDBOX_SCENARIO_NUMBERS | {SIMULATED_FAILURE_NUMBER}:
        return local
    raise DomainError(
        "INVALID_INPUT",
        "That is not a Nigerian mobile number. Use 11 digits starting 070, 080, 081, 090 or 091, "
        "or +234 followed by 10 digits.",
    )
