# SPDX-License-Identifier: AGPL-3.0-or-later
"""PACT §2.1: a Brand's Agent Card. The personal-agent JWT is the one security requirement; the scheme is
named `paJwt` as the specification's text names it and also `platformJwt`, the name the PACT conformance
suite looks for (the two disagree upstream), both describing the same Bearer JWT."""

from typing import Any

from django.conf import settings

from .brands import Brand

JWT = {"httpAuthSecurityScheme": {"scheme": "Bearer", "bearerFormat": "JWT"}}
SKILLS = {
    "airtime": ("airtime", "Airtime and data", "Buy airtime or a data plan for a Nigerian phone number."),
    "send-money": ("transfers", "Send money", "Send naira to a Nigerian bank account."),
    "food-order": ("food", "Order food", "Order from a restaurant's menu, delivered in Lagos."),
    "paystack-pay": ("payments", "Pay a merchant", "Pay a merchant for something the person bought."),
}


def interface_url(brand: Brand) -> str:
    return f"{settings.PUBLIC_BASE_URL}/a2a/{brand.id}"


def document(brand: Brand) -> dict[str, Any]:
    skills = [
        {"id": SKILLS[c][0], "name": SKILLS[c][1], "description": SKILLS[c][2], "tags": [SKILLS[c][0]]}
        for c in brand.connectors
        if c in SKILLS
    ]
    return {
        "name": brand.name,
        "description": brand.description,
        "supportedInterfaces": [
            {"url": interface_url(brand), "protocolBinding": "HTTP+JSON", "protocolVersion": "1.0"}
        ],
        "provider": {"organization": "234", "url": settings.PUBLIC_BASE_URL},
        "version": "0.1.0",
        "capabilities": {"streaming": False, "pushNotifications": False, "extendedAgentCard": False},
        "securitySchemes": {"paJwt": JWT, "platformJwt": JWT},
        "securityRequirements": [{"schemes": {"paJwt": {"list": []}}}],
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain"],
        "skills": skills,
    }
