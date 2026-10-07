# SPDX-License-Identifier: AGPL-3.0-or-later
"""A personal agent for the tests: ES256 and RS256 keys made here, a JWKS of their public halves, and tokens
signed the way PACT §3.2 asks (or the ways it forbids). Also the rig both PACT test files run on: the
registered agents and Brands, a backend whose turn writes a finished reply into the log (with whatever tool
events a test scripts), the requests, and the host's own signing key for PACT Delegated."""

import base64
import contextlib
import json
import time

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

from chat.models import Event
from pact import agents, brands, signing
from turns import kinds

ISSUER = "https://pa.example"
AUDIENCE = "234-pact-test-audience"


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def number(n: int) -> str:
    return b64(n.to_bytes((n.bit_length() + 7) // 8, "big"))


class Agent:
    def __init__(self) -> None:
        self.ec = ec.generate_private_key(ec.SECP256R1())
        self.rsa = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def jwks(self) -> bytes:
        e = self.ec.public_key().public_numbers()
        r = self.rsa.public_key().public_numbers()
        return json.dumps({"keys": [
            {"kty": "EC", "crv": "P-256", "kid": "ec-1", "alg": "ES256",
             "x": b64(e.x.to_bytes(32, "big")), "y": b64(e.y.to_bytes(32, "big"))},
            {"kty": "RSA", "kid": "rsa-1", "alg": "RS256", "n": number(r.n), "e": number(r.e)},
        ]}).encode()  # fmt: skip

    def token(self, sub="user-1", alg="ES256", kid=None, now=None, **claims) -> str:
        at = int(time.time() if now is None else now)
        body = {"iss": ISSUER, "sub": sub, "aud": AUDIENCE, "iat": at, "exp": at + 120, **claims}
        body = {k: v for k, v in body.items() if v is not None}
        header = {"alg": alg, "kid": kid or ("ec-1" if alg == "ES256" else "rsa-1"), "typ": "JWT"}
        signing = f"{b64(json.dumps(header).encode())}.{b64(json.dumps(body).encode())}".encode()
        if alg == "ES256":
            r, s = decode_dss_signature(self.ec.sign(signing, ec.ECDSA(hashes.SHA256())))
            signature = r.to_bytes(32, "big") + s.to_bytes(32, "big")
        elif alg == "RS256":
            signature = self.rsa.sign(signing, padding.PKCS1v15(), hashes.SHA256())
        else:
            import hashlib
            import hmac

            signature = hmac.new(b"not-an-allowed-key", signing, hashlib.sha256).digest()
        return f"{signing.decode()}.{b64(signature)}"


@contextlib.contextmanager
def pact_installed(settings, monkeypatch, agent, backend, brand_list):
    settings.PACT_AUDIENCE = AUDIENCE
    settings.PACT_BRANDS = brand_list
    settings.PACT_AGENTS = json.dumps([
        {"issuer": ISSUER, "jwks_uri": "https://pa.example/jwks.json"},
        {"issuer": f"{ISSUER}/disabled-pa", "jwks_uri": "https://pa.example/jwks.json", "enabled": False},
    ])  # fmt: skip
    caches = (agents.registry, agents.keys_of, brands.brands, signing.key)
    for cached in caches:
        cached.cache_clear()
    monkeypatch.setattr(
        "pact.agents.fetch", lambda url: (200, {"cache-control": "max-age=600"}, agent.jwks())
    )

    def submit(chat_id, kind, text, task=None, scopes=None):
        task = f"t{Event.objects.filter(chat_id=chat_id).count()}"
        seq = Event.objects.filter(chat_id=chat_id).count()
        said = {"text": text} if scopes is None else {"text": text, "scopes": scopes}
        for offset, (kind_, payload) in enumerate([
            (kinds.USER, said),
            (kinds.TURN_STARTED, {"task": task}),
            *backend.tools_for(text, scopes),
            (kinds.ASSISTANT, {"message": f"m{seq}", "text": f"You said: {text}"}),
            (kinds.TURN_FINISHED, {"task": task, "reason": kinds.COMPLETED}),
        ]):  # fmt: skip
            Event.objects.create(
                chat_id=chat_id, seq=seq + offset + 1, type=kind_, task=task, payload=payload, created_at=0
            )
        backend.submitted.append((chat_id, kind, text, task))
        backend.scopes.append(scopes)
        return {"seq": seq + 1, "task": task}

    backend.tools_for = lambda text, scopes: []
    backend.submit = submit
    yield
    for cached in caches:
        cached.cache_clear()


def call(client, agent, route, method="POST", body=None, token="default", brand="234", **headers):
    if token == "default":
        token = agent.token()
    if token:
        headers["HTTP_AUTHORIZATION"] = f"Bearer {token}"
    data = body if isinstance(body, str) else json.dumps(body) if body is not None else ""
    return client.generic(method, f"/a2a/{brand}/{route}", data, content_type="application/json", **headers)


def message(text="hi", **fields):
    return {
        "message": {
            "messageId": fields.pop("messageId", f"m-{time.time_ns()}"),
            "role": "ROLE_USER",
            "parts": [{"text": text}],
            **fields,
        }
    }


def envelope(answer, http, status, reason):
    body = answer.json()
    assert answer.status_code == http and answer["Content-Type"] == "application/a2a+json"
    assert body["error"]["code"] == http and body["error"]["status"] == status
    assert body["error"]["details"][0] == {
        "@type": "type.googleapis.com/google.rpc.ErrorInfo",
        "reason": reason,
        "domain": "a2a-protocol.org",
    }
    return body["error"]["message"]


def host_signing_key() -> str:
    """PACT_SIGNING_KEY for the tests: an RSA 2048 private JWK, as tools/pact-key.mjs makes."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    p = key.private_numbers()
    return json.dumps({
        "kty": "RSA", "kid": "host-test", "n": number(p.public_numbers.n), "e": number(p.public_numbers.e),
        "d": number(p.d), "p": number(p.p), "q": number(p.q), "dp": number(p.dmp1), "dq": number(p.dmq1),
        "qi": number(p.iqmp),
    })  # fmt: skip


def verified_by(jwks: dict, token: str) -> dict:
    """The claims of a JWS whose RS256 signature the published key verifies (by `cryptography`, not the
    host's own code); raises if it does not."""
    head, body, signature = token.split(".")
    header = json.loads(unb64(head))
    (key,) = [k for k in jwks["keys"] if k["kid"] == header["kid"]]
    public = rsa.RSAPublicNumbers(
        int.from_bytes(unb64(key["e"]), "big"), int.from_bytes(unb64(key["n"]), "big")
    ).public_key()
    public.verify(unb64(signature), f"{head}.{body}".encode(), padding.PKCS1v15(), hashes.SHA256())
    return json.loads(unb64(body))


def unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
