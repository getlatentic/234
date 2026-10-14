# SPDX-License-Identifier: AGPL-3.0-or-later
"""The ten tools of Paystack Index's MCP server (`paystack-index` 0.0.1, read 2026-10-13): names, annotations
and input schemas as it published them, without the prose of their parameters. The simulated Index advertises
them and checks every call against them. tests/fixtures/index_tools.json holds the whole listing, and
tests/test_index_sim_contract.py keeps this the same as it."""

TOOLS: list[dict] = [
    {
        "name": "get_balance",
        "annotations": {
            "title": "Get wallet balance",
            "readOnlyHint": True,
            "idempotentHint": True,
            "openWorldHint": False,
        },
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_recent_activity",
        "annotations": {
            "title": "Recent wallet activity",
            "readOnlyHint": True,
            "idempotentHint": True,
            "openWorldHint": False,
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "source": {"type": "string", "enum": ["index", "zap"]},
                "limit": {"type": "number", "minimum": 1, "maximum": 100},
                "type": {"type": "string", "enum": ["debit", "credit"]},
                "start_date": {"type": "string"},
                "end_date": {"type": "string"},
                "cursor": {"type": "string"},
            },
        },
    },
    {
        "name": "find_items",
        "annotations": {
            "title": "Find items at a merchant",
            "readOnlyHint": True,
            "idempotentHint": True,
            "openWorldHint": True,
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "merchant_id": {"type": "string"},
                "vendor_id": {"type": "number"},
                "address_id": {"type": "number"},
                "address_query": {"type": "string"},
                "limit": {"type": "number"},
            },
        },
    },
    {
        "name": "order",
        "annotations": {
            "title": "Order from a merchant",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "merchant_id": {"type": "string"},
                "vendor_id": {"type": "number"},
                "items": {"type": "array", "items": {"type": "object"}},
                "modifier_selections": {"type": "array", "items": {"type": "object"}},
                "address_id": {"type": "number"},
                "address_query": {"type": "string"},
                "vendor_note": {"type": "string"},
                "delivery_note": {"type": "string"},
                "confirmed": {"type": "boolean"},
            },
            "required": ["merchant_id"],
        },
    },
    {
        "name": "track_order",
        "annotations": {
            "title": "Track an order",
            "readOnlyHint": True,
            "idempotentHint": True,
            "openWorldHint": False,
        },
        "inputSchema": {
            "type": "object",
            "properties": {"merchant_id": {"type": "string"}, "order_id": {"type": "string"}},
            "required": ["merchant_id", "order_id"],
        },
    },
    {
        "name": "quick_buy",
        "annotations": {
            "title": "Quick buy — airtime, data, electricity",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "enum": ["airtime", "data", "electricity"]},
                "network": {"type": "string", "enum": ["MTN", "AIRTEL", "GLO", "9MOBILE"]},
                "phone": {"type": "string"},
                "amount_naira": {"type": "number", "minimum": 50},
                "bundle_code": {"type": "string"},
                "disco": {
                    "type": "string",
                    "enum": [
                        "ikeja",
                        "eko",
                        "phed",
                        "kano",
                        "eedc",
                        "aedc",
                        "ibedc",
                        "benin",
                        "abapower",
                        "jos",
                        "kaduna",
                        "yola",
                    ],
                },
                "meter_type": {"type": "string", "enum": ["prepaid", "postpaid"]},
                "meter_number": {"type": "string"},
                "confirmed": {"type": "boolean"},
            },
            "required": ["category"],
        },
    },
    {
        "name": "find_beneficiaries",
        "annotations": {
            "title": "Find saved Zap beneficiaries",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
            "moves_money": False,
        },
        "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": []},
    },
    {
        "name": "request_transfer_approval",
        "annotations": {
            "title": "Request transfer approval",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": True,
            "moves_money": False,
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "bank_code": {"type": "string"},
                "bank_name": {"type": "string"},
                "account_number": {"type": "string"},
                "beneficiary_code": {"type": "string"},
                "amount_naira": {"type": "number", "minimum": 100},
                "reason": {"type": "string"},
                "confirmed": {"type": "boolean"},
                "approval_token": {"type": "string"},
                "list_banks": {"type": "boolean"},
            },
            "required": [],
        },
    },
    {
        "name": "connect_merchant",
        "annotations": {
            "title": "Link a merchant account",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "merchant_id": {"type": "string"},
                "phone": {"type": "string"},
                "otp": {"type": "string"},
            },
            "required": ["merchant_id"],
        },
    },
    {
        "name": "browse_merchants",
        "annotations": {
            "title": "Browse the merchant directory",
            "readOnlyHint": True,
            "idempotentHint": True,
            "openWorldHint": False,
        },
        "inputSchema": {
            "type": "object",
            "properties": {"category": {"type": "string"}, "include_coming_soon": {"type": "boolean"}},
        },
    },
]
