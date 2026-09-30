# SPDX-License-Identifier: AGPL-3.0-or-later
"""What Paystack's popup (Inline v2, `resumeTransaction(access_code)`) needs from the page that opens it,
as a card declares it in `_meta.ui.csp` (ext-apps specification 2026-01-26). The popup is Paystack's own
script, which puts Paystack's checkout in a frame of its own; the host lets a card have these two origins
and no others.
"""

INLINE_CHECKOUT_CSP = {
    "resourceDomains": ["https://js.paystack.co"],
    "frameDomains": ["https://checkout.paystack.com"],
}
