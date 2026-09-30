# SPDX-License-Identifier: AGPL-3.0-or-later
from ..errors import DomainError
from ..paystack.api import PaystackError
from ..vtpass.api import VtpassError


def as_domain_error(error: Exception, doing: str) -> Exception:
    """A provider failure in words the model and the person can act on. Anything unexpected is left as it "
    "is."""
    if isinstance(error, PaystackError):
        advice = " This may be temporary; try again." if error.retryable else ""
        return DomainError("PROVIDER_ERROR", f"Paystack could not {doing}: {error}{advice}")
    if isinstance(error, VtpassError):
        return DomainError("PROVIDER_ERROR", f"VTpass could not {doing}: {error}")
    return error
