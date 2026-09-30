# SPDX-License-Identifier: AGPL-3.0-or-later
import re

from ..clock import Clock, lagos_stamp


def vtpass_request_id(clock: Clock, quote_id: str) -> str:
    """VTpass wants the Lagos date and minute first, then anything unique."""
    return f"{lagos_stamp(clock.now())}{re.sub(r'[^A-Za-z0-9]', '', quote_id)}"
