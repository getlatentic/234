# SPDX-License-Identifier: AGPL-3.0-or-later
import re

from ..clock import Clock, lagos_stamp


def request_id_at(at: int, quote_id: str) -> str:
    """VTpass wants the Lagos date and minute first, then anything unique."""
    return f"{lagos_stamp(at)}{re.sub(r'[^A-Za-z0-9]', '', quote_id)}"


def vtpass_request_id(clock: Clock, quote_id: str) -> str:
    return request_id_at(clock.now(), quote_id)
