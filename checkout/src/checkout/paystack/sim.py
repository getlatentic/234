# SPDX-License-Identifier: AGPL-3.0-or-later
"""A Paystack that answers from local state: the same requests the real client sends, the same
reply shapes, and Paystack's documented behaviour (an unpaid checkout reads `abandoned`, a repeated
reference is refused, test transfers succeed at once). It is a `Transport`, so the real client talks
to it unchanged."""

import json
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, unquote, urlsplit

from ..transport import Reply
from .banks import simulated_bank_name
from .sim_store import PaystackSimStore, SimTransfer

SIMULATED_OTP = "123456"
PAYSTACK_TEST_ACCOUNT = "0000000000"
PAYOUTS_REFUSED_MESSAGE = "You cannot initiate third party payouts as a starter business"

_REFERENCE = re.compile(r"^[A-Za-z0-9.=-]+$")
_TRANSFER_REFERENCE = re.compile(r"^[a-z0-9_-]{16,50}$")
_ACCOUNT = re.compile(r"^\d{10}$")


@dataclass(frozen=True)
class Call:
    body: dict[str, Any]
    query: dict[str, str]
    params: tuple[str, ...]


Handler = Callable[[Call], Awaitable[Reply]]


def ok(message: str, data: Any) -> Reply:
    return _reply(200, {"status": True, "message": message, "data": data})


def fail(status: int, message: str) -> Reply:
    return _reply(status, {"status": False, "message": message})


def _reply(status: int, body: dict[str, Any]) -> Reply:
    return Reply(status, json.dumps(body), "application/json")


def _integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdecimal():
        return int(value)
    return None


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _description_of(metadata: Any) -> str:
    try:
        fields = json.loads(_text(metadata) or "{}").get("custom_fields")
        return _text(fields[0].get("value")) or "" if fields else ""
    except ValueError, AttributeError, IndexError, TypeError:
        return ""


def _transfer_data(transfer: SimTransfer) -> dict[str, Any]:
    return {
        "status": transfer.status,
        "transfer_code": transfer.transfer_code,
        "reference": transfer.reference,
        "amount": transfer.amount_kobo,
        "currency": "NGN",
        "source": "balance",
    }


class PaystackSimulator:
    def __init__(
        self,
        store: PaystackSimStore,
        checkout_base_url: str,
        *,
        transfer_otp: bool = False,
        payouts_refused: bool = False,
    ) -> None:
        self._store = store
        self._checkout_base = checkout_base_url.rstrip("/")
        self._transfer_otp = transfer_otp
        self._payouts_refused = payouts_refused
        self._routes: tuple[tuple[str, re.Pattern[str], Handler], ...] = (
            ("POST", re.compile(r"^/transaction/initialize$"), self._initialize),
            ("GET", re.compile(r"^/transaction/verify/([^/]+)$"), self._verify),
            ("GET", re.compile(r"^/bank/resolve$"), self._resolve),
            ("POST", re.compile(r"^/transferrecipient$"), self._recipient),
            ("POST", re.compile(r"^/transfer$"), self._transfer),
            ("POST", re.compile(r"^/transfer/finalize_transfer$"), self._finalize),
            ("GET", re.compile(r"^/transfer/verify/([^/]+)$"), self._verify_transfer),
        )

    async def send(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: str | None,
        timeout_seconds: float,
    ) -> Reply:
        del timeout_seconds
        if not _header(headers, "authorization").startswith("Bearer sk_test_"):
            return fail(401, "Invalid key")
        parts = urlsplit(url)
        for route_method, pattern, handle in self._routes:
            match = pattern.match(parts.path)
            if route_method == method and match:
                call = Call(
                    _json_object(body), _query(parts.query), tuple(unquote(g) for g in match.groups())
                )
                return await handle(call)
        return fail(404, "Route not found")

    async def _initialize(self, call: Call) -> Reply:
        body = call.body
        amount, email, reference = (
            _integer(body.get("amount")),
            _text(body.get("email")),
            _text(body.get("reference")),
        )
        if not email or "@" not in email:
            return fail(400, "Invalid Email Address Passed")
        if amount is None or amount <= 0:
            return fail(400, "Invalid Amount Passed")
        if reference is None or not _REFERENCE.match(reference):
            return fail(400, "Invalid Reference Passed")
        created = await self._store.add_transaction(
            reference,
            amount,
            _text(body.get("currency")) or "NGN",
            email,
            _description_of(body.get("metadata")),
        )
        if not created:
            return fail(400, "Duplicate Transaction Reference")
        return ok(
            "Authorization URL created",
            {
                "authorization_url": f"{self._checkout_base}/{reference}",
                "access_code": reference,
                "reference": reference,
            },
        )

    async def _verify(self, call: Call) -> Reply:
        transaction = await self._store.transaction(call.params[0])
        if transaction is None:
            return fail(400, "Transaction reference not found")
        return ok(
            "Verification successful",
            {
                "status": transaction.status,
                "reference": transaction.reference,
                "amount": transaction.amount_kobo,
                "currency": transaction.currency,
                "gateway_response": transaction.gateway_response or "The transaction was not completed",
                "paid_at": transaction.paid_at,
                "channel": "card",
            },
        )

    async def _resolve(self, call: Call) -> Reply:
        account, bank = call.query.get("account_number", ""), call.query.get("bank_code", "")
        if not _ACCOUNT.match(account) or not bank or account.startswith("9999"):
            return fail(422, "Could not resolve account name. Check parameters or try again.")
        name = (
            "PAYSTACK TEST ACCOUNT"
            if account == PAYSTACK_TEST_ACCOUNT
            else f"SIMULATED ACCOUNT {account[-4:]}"
        )
        return ok("Account number resolved", {"account_number": account, "account_name": name})

    async def _recipient(self, call: Call) -> Reply:
        body = call.body
        name, account, bank = (
            _text(body.get("name")),
            _text(body.get("account_number")),
            _text(body.get("bank_code")),
        )
        if body.get("type") != "nuban" or not name or not account or not bank:
            return fail(400, "Invalid recipient details")
        row = await self._store.ensure_recipient(account, bank, name, simulated_bank_name(bank))
        return ok(
            "Transfer recipient created successfully",
            {
                "recipient_code": row.recipient_code,
                "name": row.name,
                "type": "nuban",
                "currency": "NGN",
                "details": {
                    "account_number": row.account_number,
                    "bank_code": row.bank_code,
                    "bank_name": row.bank_name,
                },
            },
        )

    async def _transfer(self, call: Call) -> Reply:
        if self._payouts_refused:
            return fail(400, PAYOUTS_REFUSED_MESSAGE)
        body = call.body
        reference, amount, recipient = (
            _text(body.get("reference")),
            _integer(body.get("amount")),
            _text(body.get("recipient")),
        )
        if reference is None or not _TRANSFER_REFERENCE.match(reference):
            return fail(400, "Invalid transfer reference")
        if amount is None or amount <= 0:
            return fail(400, "Invalid amount")
        if recipient is None or await self._store.recipient_by_code(recipient) is None:
            return fail(400, "Recipient specified is invalid")
        transfer = await self._store.ensure_transfer(
            reference, recipient, amount, "otp" if self._transfer_otp else "success"
        )
        if transfer.amount_kobo != amount or transfer.recipient_code != recipient:
            return fail(400, "This transfer reference was already used for a different transfer")
        message = (
            "Transfer requires OTP to continue" if transfer.status == "otp" else "Transfer has been queued"
        )
        return ok(message, _transfer_data(transfer))

    async def _finalize(self, call: Call) -> Reply:
        found = await self._store.transfer_by_code(_text(call.body.get("transfer_code")) or "")
        if found is None:
            return fail(400, "Transfer code is invalid")
        if found.status != "otp":
            return fail(400, "Transfer is not awaiting an OTP")
        if call.body.get("otp") != SIMULATED_OTP:
            return fail(400, "Invalid OTP")
        await self._store.finalize_transfer(found.transfer_code)
        done = await self._store.transfer_by_code(found.transfer_code)
        return ok("Transfer has been queued", _transfer_data(done or found))

    async def _verify_transfer(self, call: Call) -> Reply:
        found = await self._store.transfer_by_reference(call.params[0])
        return ok("Transfer retrieved", _transfer_data(found)) if found else fail(404, "Transfer not found")


def _header(headers: Mapping[str, str], name: str) -> str:
    return next((v for k, v in headers.items() if k.lower() == name), "")


def _json_object(body: str | None) -> dict[str, Any]:
    try:
        parsed = json.loads(body) if body else {}
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _query(query: str) -> dict[str, str]:
    return dict(parse_qsl(query))
