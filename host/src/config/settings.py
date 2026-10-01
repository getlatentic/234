# SPDX-License-Identifier: AGPL-3.0-or-later
"""Django settings for the checkout chat host.

One settings module serves the Cloudflare Worker (database D1), the static-asset build
(WORKERS_CI=1, which only runs collectstatic) and local development and tests (SQLite).
Every environment-specific value is read through ``config.runtime``.
"""

import re
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

from accounts.keys import GOOGLE_KEYS_URL
from config import runtime
from turns.settings import Settings as TurnSettings

BASE_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BASE_DIR.parent

DEBUG = runtime.get_bool("DJANGO_DEBUG", default=False)

_INSECURE_DEV_KEY = "insecure-development-key-never-use-in-production"
SECRET_KEY = (
    runtime.get("DJANGO_SECRET_KEY", _INSECURE_DEV_KEY)
    if DEBUG or runtime.IS_STATIC_BUILD
    else runtime.require("DJANGO_SECRET_KEY")
)

ALLOWED_HOSTS = runtime.get_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = runtime.get_list("DJANGO_CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "django.contrib.staticfiles",
    "chat",
    "accounts",
    "a2a",
    "ops",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "chat.security.ContentSecurityPolicyMiddleware",
    "accounts.middleware.AccountMiddleware",
    "chat.visitor.VisitorMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

# The product's name: the page title, the composer's "Ask <name>", the manifest, the description and the
# application-name meta. The wordmark drawn on the home is the same name, spelled as paths.
PRODUCT_NAME = "234"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "chat.context.product",
                "accounts.context.account",
            ]
        },
    }
]


def _databases() -> dict:
    if runtime.IS_STATIC_BUILD:
        return {}
    if runtime.IS_WORKER:
        return {"default": {"ENGINE": "django_cf.db.backends.d1", "CLOUDFLARE_BINDING": "DB"}}
    return {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": runtime.get("SQLITE_PATH", str(PROJECT_DIR / "db.sqlite3")),
        }
    }


DATABASES = _databases()
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LANGUAGE_CODE = "en"
TIME_ZONE = "UTC"
USE_I18N = False
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = PROJECT_DIR / "staticfiles" / "static"
STATICFILES_DIRS = [PROJECT_DIR / "build"]

X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    # stdout: the Workers console marks everything on stderr as an error.
    "handlers": {"console": {"class": "logging.StreamHandler", "stream": "ext://sys.stdout"}},
    "root": {"handlers": ["console"], "level": runtime.get("LOG_LEVEL", "INFO")},
}

# --- The connectors the host talks to, and what only the host may know -----

CHECKOUT_MCP_URL = runtime.get("CHECKOUT_MCP_URL", "http://localhost:8787")
CONNECTORS = runtime.get_list("CONNECTORS", ",".join(TurnSettings.connectors))
PUBLIC_BASE_URL = runtime.get("PUBLIC_BASE_URL", "http://localhost:8790").rstrip("/")
OPS_TOKEN = runtime.get("OPS_TOKEN", "")
WEBHOOK_SECRET = runtime.get("WEBHOOK_SECRET", "")

# --- The card sandbox (ext-apps "Sandbox proxy"): docs/mcp-apps-compliance.md ------

# The origin of the sandbox Worker that frames every card. It must be another origin than PUBLIC_BASE_URL, on
# its own hostname; a card cannot be shown without it.
SANDBOX_ORIGIN = runtime.get("SANDBOX_ORIGIN", "").rstrip("/")
if SANDBOX_ORIGIN and SANDBOX_ORIGIN == PUBLIC_BASE_URL:
    raise ImproperlyConfigured("SANDBOX_ORIGIN must be a different origin from PUBLIC_BASE_URL.")
# The browser features the host lets a card use; a resource may ask for camera, microphone, geolocation or
# clipboardWrite, and gets only what is listed here. None by default: no card of ours needs one.
CARD_GRANTED_PERMISSIONS = runtime.get_list("CARD_GRANTED_PERMISSIONS")
# Inline Paystack checkout: lets a card that declares js.paystack.co (script) and checkout.paystack.com
# (frame) have them. Off, those origins are refused and the card opens the checkout in a new tab.
INLINE_PAYSTACK = runtime.get_bool("INLINE_PAYSTACK", default=True)
# Origins any card may declare, in every field, besides the Paystack ones above (defence against a compromised
# connector); and the connectors whose declared image origins are taken as they come.
CARD_ALLOWED_ORIGINS = runtime.get_list("CARD_ALLOWED_ORIGINS")
CARD_IMAGE_SERVERS = runtime.get_list("CARD_IMAGE_SERVERS", "food-order")

# Other agents: a bearer token each (`name:token,...`, a secret), and the sites that may call from a browser.
A2A_TOKENS = runtime.get("A2A_TOKENS", "")
A2A_CORS_ORIGINS = runtime.get_list("A2A_CORS_ORIGINS")
if "*" in A2A_CORS_ORIGINS:
    raise ImproperlyConfigured("A2A_CORS_ORIGINS lists the sites that may call; it cannot be *.")

# --- Sign in with Google through Firebase (docs/auth.md) --------------------------------

# The Firebase project and its web app's public identifiers, and ACCOUNT_KEY (a secret, the key that turns a
# Firebase uid into an owner). Sign-in exists only when all four are set: without them the page has no button
# and the endpoints answer 404, and the site works as it did.
FIREBASE_PROJECT_ID = runtime.get("FIREBASE_PROJECT_ID", "")
FIREBASE_API_KEY = runtime.get("FIREBASE_API_KEY", "")
FIREBASE_AUTH_DOMAIN = runtime.get("FIREBASE_AUTH_DOMAIN", "")
ACCOUNT_KEY = runtime.get("ACCOUNT_KEY", _INSECURE_DEV_KEY if DEBUG else "")
# The static build holds no secret; it needs to know whether sign-in is on, for the home shell and its policy.
_SIGN_IN_KEY = ACCOUNT_KEY or runtime.IS_STATIC_BUILD
SIGN_IN_ENABLED = all((FIREBASE_PROJECT_ID, FIREBASE_API_KEY, FIREBASE_AUTH_DOMAIN, _SIGN_IN_KEY))
# Development only: the Firebase Auth emulator (host:port) and a stand-in for Google's key document. Setting
# either outside development is refused at startup, so no public configuration can accept an unsigned token.
FIREBASE_AUTH_EMULATOR_HOST = runtime.get("FIREBASE_AUTH_EMULATOR_HOST", "")
FIREBASE_KEYS_URL = runtime.get("FIREBASE_KEYS_URL", GOOGLE_KEYS_URL)
if (FIREBASE_AUTH_EMULATOR_HOST or FIREBASE_KEYS_URL != GOOGLE_KEYS_URL) and (
    not DEBUG or runtime.get_bool("REQUIRE_OWNER")
):
    raise ImproperlyConfigured("FIREBASE_AUTH_EMULATOR_HOST and FIREBASE_KEYS_URL are for development only.")
if not re.fullmatch(r"[a-z0-9.-]*", FIREBASE_AUTH_DOMAIN):
    raise ImproperlyConfigured("FIREBASE_AUTH_DOMAIN is a host name.")
if not re.fullmatch(r"[a-z0-9.:-]*", FIREBASE_AUTH_EMULATOR_HOST):
    raise ImproperlyConfigured("FIREBASE_AUTH_EMULATOR_HOST is host:port.")
# The sign-in popup opens a window that keeps its link to ours: the default, same-origin, would cut it.
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin-allow-popups" if SIGN_IN_ENABLED else "same-origin"
