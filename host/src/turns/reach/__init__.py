# SPDX-License-Identifier: AGPL-3.0-or-later
"""234 as a person's own agent at other Brands, over PACT (openpactprotocol.org): the `brands` connector the
model is offered, served by the host itself (server.py). It signs a personal-agent JWT for each message,
keeps the conversation with each Brand, asks the person to sign in at a Brand when the Brand needs their
permission, and checks every receipt the Brand signs."""
