# SPDX-License-Identifier: AGPL-3.0-or-later
"""What a signed-in session is and does once the token is verified: the owner derived from the uid, the
session cookie's flags, the CSRF check on the sign-in POST, the adoption of an anonymous visitor's chats, and
the page policy's narrow sign-in origins. Run against the host's own tests."""

from tools.mutations.model import Mutation
from tools.mutations.model import host_mutation as host

ACCOUNTS = ["tests/test_accounts.py"]
VISITOR = ["tests/test_visitor.py"]
CORE = ["tests/test_chat_core.py"]


def cookie(guardrail: str, find: str, replace: str) -> Mutation:
    return host(guardrail, "accounts/session.py", find, replace, ACCOUNTS)


def adoption(guardrail: str, file: str, find: str, replace: str) -> Mutation:
    return host(guardrail, file, find, replace, ACCOUNTS)


MUTATIONS: list[Mutation] = [
    host(
        "the owner of an account is keyed by ACCOUNT_KEY",
        "accounts/owner.py",
        "hmac.new(key.encode(),",
        'hmac.new(b"",',
        ACCOUNTS,
    ),
    host(
        "the owner of an account is its own: one per uid",
        "accounts/owner.py",
        'f"account-owner:{uid}".encode()',
        '"account-owner:".encode()',
        ACCOUNTS,
    ),
    host(
        "the owner is made with ACCOUNT_KEY and not with the Django key",
        "accounts/views.py",
        "account_owner(identity.uid, settings.ACCOUNT_KEY)",
        "account_owner(identity.uid, settings.SECRET_KEY)",
        ACCOUNTS,
    ),
    host(
        "the owner comes from the uid, which never changes, and not from the email, which can",
        "accounts/views.py",
        "account_owner(identity.uid, settings.ACCOUNT_KEY)",
        "account_owner(identity.email, settings.ACCOUNT_KEY)",
        ACCOUNTS,
    ),
    cookie("the session cookie is HttpOnly", "httponly=True,", "httponly=False,"),
    cookie(
        "the session cookie is SameSite=Lax",
        'httponly=True, samesite="Lax", secure',
        'httponly=True, samesite="None", secure',
    ),
    cookie(
        "the session cookie is Secure outside development",
        'secure=not settings.DEBUG, path="/"',
        'secure=False, path="/"',
    ),
    cookie(
        "the session cookie is host-only: it names no domain",
        'secure=not settings.DEBUG, path="/"',
        'secure=not settings.DEBUG, path="/", domain="example.com"',
    ),
    cookie(
        "a session cookie has a lifetime of thirty days",
        "max_age=LIFETIME, httponly",
        "max_age=None, httponly",
    ),
    cookie(
        "a session cookie older than its lifetime is not a session",
        "signing.loads(raw, salt=SALT, max_age=LIFETIME)",
        "signing.loads(raw, salt=SALT)",
    ),
    cookie(
        "the session value is new at every sign-in",
        '"n": secrets.token_hex(8)',
        '"n": "0"',
    ),
    cookie(
        "a cookie signed for another purpose is not a session",
        "signing.loads(raw, salt=SALT, max_age=LIFETIME)",
        "signing.loads(raw, salt='', max_age=LIFETIME)",
    ),
    host(
        "signing out ends the session",
        "accounts/views.py",
        "        session.end(response)\n",
        "        pass\n",
        ACCOUNTS,
    ),
    host(
        "a sign-in is a POST behind the CSRF check",
        "accounts/views.py",
        "from django.views.decorators.http import require_POST\n",
        "from django.views.decorators.csrf import csrf_exempt\n"
        "from django.views.decorators.http import require_POST as _post\n\n"
        "require_POST = lambda view: csrf_exempt(_post(view))\n",
        ACCOUNTS,
    ),
    host(
        "a sign-in is rate limited per client",
        "accounts/views.py",
        'if not get_backend().rate_ok(f"auth:{_client(request)}"):',
        "if False:",
        ACCOUNTS,
    ),
    host(
        "a deployment without sign-in answers no sign-in request",
        "accounts/views.py",
        "    if not settings.SIGN_IN_ENABLED:\n        raise Http404\n    if not get_backend()",
        "    if False:\n        raise Http404\n    if not get_backend()",
        ACCOUNTS,
    ),
    host(
        "a deployment without sign-in has no accounts, whatever cookie arrives",
        "accounts/middleware.py",
        "session.read(request) if settings.SIGN_IN_ENABLED else None",
        "session.read(request)",
        ACCOUNTS,
    ),
    host(
        "a signed-in person's chats are their account's, not a visitor's",
        "chat/visitor.py",
        'account.owner if account else f"{OWNER_PREFIX}{visitor}"',
        'f"{OWNER_PREFIX}{visitor}"',
        ACCOUNTS,
    ),
    host(
        "a signed-in person gets no visitor cookie",
        "chat/visitor.py",
        "if known is None and account is None and",
        "if known is None and",
        ACCOUNTS,
    ),
    host(
        "the visitor cookie is dropped at sign-in",
        "accounts/views.py",
        "    visitor.forget(response)\n",
        "    pass\n",
        ACCOUNTS,
    ),
    host(
        "a chat's owner is read each time: a chat adopted while its object lives is spent for by the account",
        "turns/chat_core.py",
        'return row["owner"]',
        'return self.__dict__.setdefault("_kept", row["owner"])',
        CORE,
    ),
    adoption(
        "adoption moves only the signed-in person's own anonymous chats",
        "accounts/adopt.py",
        "Chat.objects.filter(owner=visitor_owner).update(owner=account_owner)",
        "Chat.objects.update(owner=account_owner)",
    ),
    adoption(
        "a guest pass the account already holds is not duplicated by adoption",
        "accounts/adopt.py",
        "Q(chat__owner=account_owner) | Q(chat_id__in=already)",
        "Q(pk__in=[])",
    ),
    adoption(
        "chats are adopted only by a person who was anonymous",
        "accounts/views.py",
        "if anonymous is not None and request.account is None:",
        "if anonymous is not None:",
    ),
    adoption(
        "adoption happens only for a visitor the cookie proves",
        "accounts/views.py",
        'adopt(f"{visitor.OWNER_PREFIX}{anonymous}", owner)',
        "adopt(f\"{visitor.OWNER_PREFIX}{json_body(request).get('visitor')}\", owner)",
    ),
    host(
        "the sign-in popup's frame is the auth domain alone",
        "chat/security.py",
        'sources["frame-src"] = [f"https://{settings.FIREBASE_AUTH_DOMAIN}"]',
        'sources["frame-src"] = ["https:"]',
        ACCOUNTS,
    ),
    host(
        "the sign-in loader script is one host",
        "chat/security.py",
        '"script-src": ["https://apis.google.com"],',
        '"script-src": ["https:"],',
        ACCOUNTS,
    ),
    host(
        "a deployment without sign-in adds nothing to the page policy",
        "chat/security.py",
        "    if not settings.SIGN_IN_ENABLED:\n        return {}",
        "    if False:\n        return {}",
        ACCOUNTS,
    ),
    host(
        "the emulator's origin is in the page policy only where the emulator is configured",
        "chat/security.py",
        "if settings.FIREBASE_AUTH_EMULATOR_HOST:",
        "if True:",
        ACCOUNTS,
    ),
]
