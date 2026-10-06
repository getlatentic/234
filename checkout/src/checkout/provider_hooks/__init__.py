# SPDX-License-Identifier: AGPL-3.0-or-later
"""What Paystack and VTpass tell the connectors by webhook. A webhook carries no authority: it names a
reference, and the quote it belongs to is checked again with the provider's own API, as the card's status read
checks it. A forged or repeated webhook costs one such check, and only for a quote that is still pending."""
