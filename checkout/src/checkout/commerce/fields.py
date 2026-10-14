# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the buyer gives a merchant (a delivery area, a customer number), read against the fields the merchant
asks for. A value outside what a field allows is refused, naming the field, and nothing else is accepted."""

import re
from collections.abc import Mapping

from ..errors import DomainError
from .model import FieldSpec, Merchant
from .text import third_party

MAX_FIELDS = 8
_SEPARATORS = re.compile(r"[\s-]")


def _digits(spec: FieldSpec, value: str) -> str:
    found = _SEPARATORS.sub("", value)
    if not found.isdecimal() or not spec.least <= len(found) <= spec.most:
        raise DomainError(
            "FIELD_INVALID",
            f"{spec.label} must be {spec.least} to {spec.most} digits. Ask the person for it.",
        )
    return found


def _choice(spec: FieldSpec, value: str) -> str:
    found = next((option for option in spec.options if option.lower() == value.lower()), None)
    if found is None:
        raise DomainError("FIELD_INVALID", f"{spec.label} must be one of: {', '.join(spec.options)}.")
    return found


def _text(spec: FieldSpec, value: str) -> str:
    if not value or len(value) > spec.most:
        raise DomainError("FIELD_INVALID", f"{spec.label} must be 1 to {spec.most} characters.")
    return value


def _read(spec: FieldSpec, value: str) -> str:
    cleaned = third_party(value, spec.most + 1)
    match spec.kind:
        case "digits":
            return _digits(spec, cleaned)
        case "choice":
            return _choice(spec, cleaned)
        case _:
            return _text(spec, cleaned)


def buyer_fields(merchant: Merchant, given: Mapping[str, str]) -> tuple[tuple[str, str, str], ...]:
    """The fields as (name, label, value) in the merchant's order, each valid, none unknown."""
    if len(given) > MAX_FIELDS:
        raise DomainError("FIELD_INVALID", f"At most {MAX_FIELDS} fields.")
    known = {spec.name: spec for spec in merchant.fields}
    unknown = sorted(set(given) - set(known))
    if unknown:
        asked = ", ".join(spec.name for spec in merchant.fields) or "nothing"
        raise DomainError(
            "FIELD_INVALID", f'{merchant.name} does not take "{unknown[0]}". It asks for: {asked}.'
        )
    read: list[tuple[str, str, str]] = []
    for spec in merchant.fields:
        value = given.get(spec.name)
        if value is None or not str(value).strip():
            if spec.required:
                raise DomainError(
                    "FIELD_REQUIRED",
                    f"{merchant.name} needs {spec.label} ({spec.name}): pass it from what the person "
                    "said, or ask for it if they gave none.",
                )
            continue
        read.append((spec.name, spec.label, _read(spec, str(value))))
    return tuple(read)
