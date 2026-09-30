# SPDX-License-Identifier: AGPL-3.0-or-later
"""Sign in with Google against the running Worker, its D1 and its Durable Objects, with real RS256.

Tokens are signed here with the key of the stand-in for Google's key document (tools/up.sh with AUTH=1 or
AUTH=keys writes it to .stack/<base>/keys/); the Worker fetches the public half over HTTP, as it would
Google's.

Run with the stack up, and say which one you started: `AUTH=1 HOST_URL=http://localhost:8921 pytest -m worker
tests/test_worker_auth.py` (the emulator is configured, so an unsigned emulator token is accepted) or with
`AUTH=keys` (as in public: it is refused). The tests skip when the host has no sign-in."""

import base64
import itertools
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from .worker_client import HOST, Visitor, finished, reset_budget, until

pytestmark = pytest.mark.worker
PORT = urlparse(HOST).port or 0
KEY_DIR = Path(__file__).resolve().parents[2] / ".stack" / str(PORT - 1) / "keys"
EMULATOR = os.environ.get("AUTH") == "1"
PROJECT = "demo-twothreefour"
PAY = "Buy ₦500 MTN airtime for 08031234567"
CHATS = re.compile(r'href="/c/([0-9a-f]{32})/"')


ADDRESSES = itertools.count(1)


def post_auth(visitor: Visitor, path: str, body: dict, address: str | None = None) -> httpx.Response:
    """A POST as the edge would deliver it: the limiter counts per client address, which Cloudflare puts in
    CF-Connecting-IP, so each test gets an address of its own and one test can exhaust one."""
    n = next(ADDRESSES)
    headers = {"X-CSRFToken": visitor.csrf, "CF-Connecting-IP": address or f"10.7.{n // 250}.{n % 250 + 1}"}
    return visitor.http.post(path, headers=headers, json=body)


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def claims(uid: str, **changes) -> dict:
    now = int(time.time())
    base = {
        "iss": f"https://securetoken.google.com/{PROJECT}", "aud": PROJECT, "sub": uid,
        "email": f"{uid}@example.com", "email_verified": True,
        "auth_time": now, "iat": now, "exp": now + 3600, "firebase": {"sign_in_provider": "google.com"},
    }  # fmt: skip
    return base | changes


def signed(payload: dict, alg: str = "RS256", private=None) -> str:
    key = private or serialization.load_pem_private_key((KEY_DIR / "private.pem").read_bytes(), None)
    header = {"alg": alg, "typ": "JWT", "kid": (KEY_DIR / "kid").read_text().strip()}
    signing_input = f"{b64(json.dumps(header).encode())}.{b64(json.dumps(payload).encode())}"
    return f"{signing_input}.{b64(key.sign(signing_input.encode(), padding.PKCS1v15(), hashes.SHA256()))}"


@pytest.fixture(autouse=True)
async def fresh_budget():
    await reset_budget()
    if not (KEY_DIR / "private.pem").exists():
        pytest.skip("the stack was not started with AUTH=1 or AUTH=keys")
    async with httpx.AsyncClient() as probe:
        if "chat-account" not in (await probe.get(HOST)).text:
            pytest.skip("the host has no sign-in")


async def chats(visitor: Visitor) -> set[str]:
    return set(CHATS.findall((await visitor.http.get("/")).text))


async def sign_in(visitor: Visitor, uid: str, **changes) -> httpx.Response:
    return await post_auth(visitor, "/auth/session", {"idToken": signed(claims(uid, **changes))})


async def test_the_anonymous_chat_becomes_the_accounts_and_a_second_device_sees_it_and_sign_out_hides_it():
    uid = f"uid-{time.time_ns()}"
    async with Visitor() as first, Visitor() as second:
        chat = await first.new_chat()
        await first.send(chat, "echo: hello")
        await until(first.sse(chat), finished)
        assert await chats(first) == {chat}
        answer = await sign_in(first, uid)
        assert answer.status_code == 200 and answer.json() == {"email": f"{uid}@example.com"}
        assert "session" in first.http.cookies and "visitor" not in first.http.cookies
        assert await chats(first) == {chat}
        assert (await first.http.get(f"/c/{chat}/")).status_code == 200

        assert (await sign_in(second, uid)).status_code == 200
        assert await chats(second) == {chat}
        assert (await second.http.get(f"/c/{chat}/")).status_code == 200
        later = await second.send(chat, "echo: from the second device")
        assert later.status_code == 200, "the same account may speak in the chat from another device"

        assert (await post_auth(first, "/auth/signout", {})).status_code == 204
        assert "session" not in first.http.cookies or not first.http.cookies["session"]
        assert (await first.http.get(f"/c/{chat}/")).status_code == 404
        assert await chats(first) == set()


async def test_another_account_has_none_of_it():
    async with Visitor() as one, Visitor() as other:
        chat = await one.new_chat()
        await one.send(chat, "echo: private")
        await sign_in(one, f"uid-a-{time.time_ns()}")
        await sign_in(other, f"uid-b-{time.time_ns()}")
        assert (await other.http.get(f"/c/{chat}/")).status_code == 404
        assert await chats(other) == set()


async def test_the_chat_object_spends_for_the_account_once_the_chat_has_moved_to_it():
    """The Durable Object of a chat that has already run a turn is alive, or woken, after the move. A card
    call asks the connector under the owner the object reads now: the quote made for the anonymous key is
    not the account's, so approving it is refused as a quote the connector does not know."""
    async with Visitor() as v:
        chat = await v.new_chat()
        await v.send(chat, PAY)
        events = await until(v.sse(chat), finished)
        card = next(e for e in events if e["type"] == "card")["payload"]
        result = card["result"]
        quote, token = result["structuredContent"]["quote"], result["_meta"]["approvalToken"]
        await sign_in(v, f"uid-card-{time.time_ns()}")
        approve = await v.post(
            f"/c/{chat}/call",
            {
                "server": card["server"],
                "name": "approve_quote",
                "arguments": {
                    "quote_id": quote["id"], "approval_token": token,
                    "displayed_amount_kobo": quote["amount"]["kobo"], "readback_confirmed": True,
                },
            },
        )  # fmt: skip
        body = approve.json()
        assert body.get("isError") is True, body
        assert body["content"][0]["text"].startswith("QUOTE_NOT_FOUND"), body


async def test_tokens_that_are_not_signed_by_the_published_key_are_refused():
    from cryptography.hazmat.primitives.asymmetric import rsa

    stranger = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    async with Visitor() as v:
        good = signed(claims("uid-x"))
        head, body, sig = good.split(".")
        flipped = sig[:20] + ("B" if sig[20] == "A" else "A") + sig[21:]
        for bad in (
            signed(claims("uid-x"), private=stranger),
            f"{head}.{body}.{flipped}",
            signed(claims("uid-x"), alg="HS256"),
            signed(claims("uid-x", aud="another-project")),
            signed(claims("uid-x", email_verified=False)),
            signed(claims("uid-x", firebase={"sign_in_provider": "password"})),
            signed(claims("uid-x", exp=int(time.time()) - 600)),
            "garbage",
        ):
            assert (await post_auth(v, "/auth/session", {"idToken": bad})).status_code == 401, bad[:40]
        assert "session" not in v.http.cookies


async def test_an_unsigned_emulator_token_is_accepted_only_where_the_emulator_is_configured():
    unsigned = f"{b64(b'{"alg":"none","typ":"JWT"}')}.{b64(json.dumps(claims('uid-emulator')).encode())}."
    async with Visitor() as v:
        answer = await post_auth(v, "/auth/session", {"idToken": unsigned})
        assert answer.status_code == (200 if EMULATOR else 401)


async def test_sign_ins_from_one_address_are_limited_to_twelve_a_minute():
    async with Visitor() as v:
        statuses = [
            (await post_auth(v, "/auth/session", {"idToken": "garbage"}, address="10.9.9.9")).status_code
            for _ in range(14)
        ]
        assert statuses[:12] == [401] * 12 and 429 in statuses[12:], statuses


async def test_a_post_without_the_csrf_token_is_refused():
    async with httpx.AsyncClient(base_url=HOST) as bare:
        await bare.get("/")
        answer = await bare.post("/auth/session", json={"idToken": signed(claims("uid-csrf"))})
        assert answer.status_code == 403
