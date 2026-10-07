# SPDX-License-Identifier: AGPL-3.0-or-later
"""A Brand's PACT Provider for the tests of 234 as an agent: an Agent Card with a device-code scheme, a
message endpoint that checks 234's personal-agent JWT and answers, steps up when a request needs a scope the
delegation lacks, RFC 8628 device authorization whose decision the test makes, refresh, RFC 7009 revocation
(unless `revocation` is None), and receipts signed with ES256 as PACT's reference Provider signs them. It is
served by httpx.MockTransport."""

import json
import secrets
import time
from urllib.parse import parse_qs

import httpx
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

from signatures import jws
from signatures.jwks import parse

BASE = "https://provider.example"
INTERFACE = f"{BASE}/a2a/skyline"
CARD = f"{INTERFACE}/.well-known/agent-card.json"
AUDIENCE = f"{BASE}/a2a"
SCOPES = {"flights:upcoming:read": "See your upcoming flights", "flights:rebook": "Rebook a flight"}


class FakeBrand:
    def __init__(self, agent_public: dict) -> None:
        self.agent_key = parse(json.dumps({"keys": [agent_public]}).encode())[agent_public["kid"]]
        self.agent_kid = agent_public["kid"]
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.devices: dict[str, dict] = {}
        self.tokens: dict[str, dict] = {}
        self.refreshes: dict[str, dict] = {}
        self.contexts: dict[str, str] = {}
        self.seen: list[dict] = []
        self.tamper_receipt = False
        self.receipt_key = self.key
        self.receipt_pa: str | None = None
        self.reject_tokens = False
        self.revocation: int | None = 200
        """The status the revocation endpoint answers, or None for a Brand that offers none."""
        self.revoked: list[tuple[str, str]] = []

    # --- what 234 sends, checked -------------------------------------------------------------------
    def caller(self, request: httpx.Request) -> dict | None:
        scheme, _, token = request.headers.get("authorization", "").partition(" ")
        found = jws.parts(token) if scheme == "Bearer" else None
        if (
            found is None
            or found.header.get("kid") != self.agent_kid
            or not jws.signed_by(found, self.agent_key)
        ):
            return None
        claims = found.claims
        if claims.get("aud") != AUDIENCE or not claims.get("sub") or claims["exp"] - claims["iat"] > 300:
            return None
        return claims

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        routes = {
            CARD: self.card,
            f"{INTERFACE}/message:send": self.message,
            f"{BASE}/oauth/device_authorization": self.device_authorization,
            f"{BASE}/oauth/token": self.token,
            f"{BASE}/oauth/.well-known/oauth-authorization-server": self.metadata,
            f"{BASE}/oauth/jwks.json": self.jwks,
            f"{BASE}/oauth/revoke": self.revoke,
        }
        handler = routes.get(url.split("?")[0])
        return handler(request) if handler else httpx.Response(404)

    # --- the card and the keys ---------------------------------------------------------------------
    def card(self, request: httpx.Request) -> httpx.Response:
        jwt = {"httpAuthSecurityScheme": {"scheme": "Bearer", "bearerFormat": "JWT"}}
        flow = {
            "deviceAuthorizationUrl": f"{BASE}/oauth/device_authorization",
            "tokenUrl": f"{BASE}/oauth/token",
            "scopes": SCOPES,
        }
        delegation = {
            "oauth2SecurityScheme": {
                "flows": {"deviceCode": flow},
                "oauth2MetadataUrl": f"{BASE}/oauth/.well-known/oauth-authorization-server",
            }
        }
        return httpx.Response(
            200,
            json={
                "name": "Skyline Airways",
                "description": "Flight status and trip changes.",
                "supportedInterfaces": [
                    {"url": INTERFACE, "protocolBinding": "HTTP+JSON", "protocolVersion": "1.0"}
                ],
                "securitySchemes": {"platformJwt": jwt, "userDelegation": delegation},
                "securityRequirements": [
                    {"schemes": {"platformJwt": {"list": []}}},
                    {"schemes": {"platformJwt": {"list": []}, "userDelegation": {"list": []}}},
                ],
                "skills": [{"id": "flight-status", "name": "Flight status"}],
            },
        )

    def metadata(self, request: httpx.Request) -> httpx.Response:
        metadata = {
            "issuer": f"{BASE}/oauth",
            "jwks_uri": f"{BASE}/oauth/jwks.json",
            "token_endpoint": f"{BASE}/oauth/token",
            "device_authorization_endpoint": f"{BASE}/oauth/device_authorization",
        }
        if self.revocation is not None:
            metadata["revocation_endpoint"] = f"{BASE}/oauth/revoke"
        return httpx.Response(200, json=metadata)

    def jwks(self, request: httpx.Request) -> httpx.Response:
        numbers = self.key.public_key().public_numbers()
        key = {
            "kty": "EC",
            "crv": "P-256",
            "kid": "brand-1",
            "alg": "ES256",
            "x": jws.b64(numbers.x.to_bytes(32, "big")),
            "y": jws.b64(numbers.y.to_bytes(32, "big")),
        }
        return httpx.Response(200, json={"keys": [key]})

    def es256(self, claims: dict) -> str:
        head = jws.b64(json.dumps({"alg": "ES256", "kid": "brand-1"}).encode())
        body = jws.b64(json.dumps(claims).encode())
        r, s = decode_dss_signature(
            self.receipt_key.sign(f"{head}.{body}".encode(), ec.ECDSA(hashes.SHA256()))
        )
        return f"{head}.{body}.{jws.b64(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"

    # --- messages ----------------------------------------------------------------------------------
    def message(self, request: httpx.Request) -> httpx.Response:
        caller = self.caller(request)
        if caller is None:
            return httpx.Response(401, headers={"www-authenticate": 'Bearer realm="a2a"'})
        body = json.loads(request.content)["message"]
        text = body["parts"][0]["text"]
        delegation = self.delegation_of(request, caller)
        if delegation == "rejected":
            return httpx.Response(
                401, headers={"www-authenticate": 'Bearer realm="a2a", error="invalid_token"'}
            )
        self.seen.append(
            {
                "sub": caller["sub"],
                "text": text,
                "context": body.get("contextId"),
                "delegated": bool(delegation),
            }
        )
        context = body.get("contextId") or f"ctx-{secrets.token_hex(4)}"
        if body.get("contextId") and body["contextId"] not in self.contexts:
            return self.envelope("INVALID_PARAMS", "Unknown contextId")
        self.contexts[context] = caller["sub"]
        needed = (
            "flights:rebook" if "rebook" in text else "flights:upcoming:read" if "upcoming" in text else None
        )
        if needed and (not delegation or needed not in delegation["scope"].split()):
            task = {
                "id": "t-1",
                "contextId": context,
                "status": {
                    "state": "TASK_STATE_AUTH_REQUIRED",
                    "message": {
                        "messageId": "m",
                        "role": "ROLE_AGENT",
                        "parts": [{"text": "I need permission."}],
                    },
                },
                "metadata": {"pact.missingScopes": [needed]},
            }
            return httpx.Response(200, json={"task": task})
        reply = {
            "messageId": "r",
            "contextId": context,
            "role": "ROLE_AGENT",
            "parts": [{"text": f"Seen: {text}"}],
        }
        if delegation:
            claims = {
                "grantId": delegation["grant"],
                "user": "alex",
                "pa": caller["iss"],
                "brand": INTERFACE,
                "scopesUsed": [needed] if needed else [],
                "actions": [{"tool": "list_upcoming_trips"}],
                "ts": "2026-10-07T12:00:00Z",
            }
            if self.receipt_pa:
                claims["pa"] = self.receipt_pa
            shown = {**claims, "user": "someone-else"} if self.tamper_receipt else claims
            reply["metadata"] = {"pact.receipt": {"jws": self.es256(claims), "claims": shown}}
        return httpx.Response(200, json={"message": reply})

    def delegation_of(self, request: httpx.Request, caller: dict) -> dict | str | None:
        header = request.headers.get("x-a2a-user-delegation")
        if not header:
            return None
        found = self.tokens.get(header.removeprefix("Bearer "))
        if found is None or self.reject_tokens or found["sub"] != caller["sub"] or found["exp"] < time.time():
            return "rejected"
        return found

    def envelope(self, reason: str, message: str) -> httpx.Response:
        detail = {
            "@type": "type.googleapis.com/google.rpc.ErrorInfo",
            "reason": reason,
            "domain": "a2a-protocol.org",
        }
        error = {"code": 400, "status": "INVALID_ARGUMENT", "message": message, "details": [detail]}
        return httpx.Response(400, json={"error": error})

    # --- RFC 8628 ----------------------------------------------------------------------------------
    def form(self, request: httpx.Request) -> dict[str, str]:
        return {k: v[0] for k, v in parse_qs(request.content.decode()).items()}

    def device_authorization(self, request: httpx.Request) -> httpx.Response:
        caller, fields = self.caller(request), self.form(request)
        if caller is None or fields.get("client_id") != caller["iss"]:
            return httpx.Response(401, json={"error": "invalid_client"})
        code = f"dc-{secrets.token_hex(4)}"
        self.devices[code] = {
            "sub": caller["sub"],
            "scope": fields["scope"],
            "decision": None,
            "taken": False,
        }
        link = f"https://skyline.example/login?user_code={code[-4:]}"
        return httpx.Response(
            200,
            json={
                "device_code": code,
                "user_code": code[-4:],
                "verification_uri": link,
                "verification_uri_complete": link,
                "expires_in": 600,
                "interval": 5,
            },
        )

    def decide(self, allowed: str | None) -> None:
        """The person, at the Brand, allows these scopes of the latest request, or (None) says no."""
        latest = list(self.devices.values())[-1]
        latest["decision"] = allowed if allowed is not None else "denied"

    def issue(self, sub: str, scope: str, lifetime: int = 3600) -> dict:
        access, refresh = f"at-{secrets.token_hex(6)}", f"rt-{secrets.token_hex(6)}"
        self.tokens[access] = {"sub": sub, "scope": scope, "grant": "g-1", "exp": time.time() + lifetime}
        self.refreshes[refresh] = {"sub": sub, "scope": scope}
        return {
            "token_type": "Bearer",
            "access_token": access,
            "refresh_token": refresh,
            "expires_in": lifetime,
            "scope": scope,
        }

    def token(self, request: httpx.Request) -> httpx.Response:
        caller, fields = self.caller(request), self.form(request)
        if caller is None:
            return httpx.Response(401)
        if fields.get("grant_type") == "refresh_token":
            found = self.refreshes.pop(fields.get("refresh_token", ""), None)
            if found is None or found["sub"] != caller["sub"]:
                return httpx.Response(400, json={"error": "invalid_grant"})
            return httpx.Response(200, json=self.issue(found["sub"], found["scope"]))
        device = self.devices.get(fields.get("device_code", ""))
        if device is None or device["sub"] != caller["sub"] or device["taken"]:
            return httpx.Response(400, json={"error": "invalid_grant"})
        if device["decision"] is None:
            return httpx.Response(400, json={"error": "authorization_pending"})
        if device["decision"] == "denied":
            return httpx.Response(400, json={"error": "access_denied"})
        device["taken"] = True
        return httpx.Response(200, json=self.issue(device["sub"], device["decision"]))

    def revoke(self, request: httpx.Request) -> httpx.Response:
        """RFC 7009: revoking either token ends the grant, so both of its tokens stop working."""
        caller, fields = self.caller(request), self.form(request)
        if caller is None or fields.get("client_id") != caller["iss"] or self.revocation is None:
            return httpx.Response(401, json={"error": "invalid_client"})
        self.revoked.append((fields.get("token_type_hint", ""), fields["token"]))
        if self.revocation == 200:
            ended = self.tokens.pop(fields["token"], None) or self.refreshes.pop(fields["token"], None)
            if ended:
                self.tokens = {k: v for k, v in self.tokens.items() if v["sub"] != ended["sub"]}
                self.refreshes = {k: v for k, v in self.refreshes.items() if v["sub"] != ended["sub"]}
        return httpx.Response(
            self.revocation, json={} if self.revocation == 200 else {"error": "server_error"}
        )


def agent_key_pair() -> tuple[str, dict]:
    """234's agent key for the tests, a P-256 private JWK as tools/pact-key.mjs --ec makes, and its public
    half."""
    from signatures.private_key import from_jwk

    made = ec.generate_private_key(ec.SECP256R1())
    numbers = made.private_numbers()
    point = numbers.public_numbers
    private = json.dumps({
        "kty": "EC", "crv": "P-256", "kid": "234-test",
        "x": jws.b64(point.x.to_bytes(32, "big")), "y": jws.b64(point.y.to_bytes(32, "big")),
        "d": jws.b64(numbers.private_value.to_bytes(32, "big")),
    })  # fmt: skip
    return private, from_jwk(private).public()
