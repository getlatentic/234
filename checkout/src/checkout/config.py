# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the server is configured with, read once at startup from the Worker's variables and secrets.

Nothing here can reach live money: a live Paystack key is refused whatever mode is set, only
`sk_test_` keys are accepted, and simulated mode cannot sit beside a live key.
"""

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from .errors import ConfigError
from .memory.settings import MemorySettings
from .paystack.api import PAYSTACK_API_URL
from .vtpass.client import VtpassCredentials
from .web.reader import DEFAULT_DENY

CONNECTORS = ("paystack-pay", "send-money", "airtime", "food-order")
MEMORY_CONNECTOR = "memory"
CONNECTOR_MODE_VARIABLES = {
    "paystack-pay": "PAYSTACK_PAY_MODE",
    "send-money": "SEND_MONEY_MODE",
    "airtime": "AIRTIME_MODE",
    "food-order": "FOOD_ORDER_MODE",
}
# The plain PAYSTACK_SECRET_KEY name is never used, but is checked so a live key kept there is refused too.
_LIVE_KEY_HOLDERS = ("PAYSTACK_TEST_SECRET_KEY", "PAYSTACK_SECRET_KEY")
_TEST_KEY = re.compile(r"sk_test_[A-Za-z0-9]{8,}")
_TRUE = ("1", "true", "yes", "on")
_FALSE = ("0", "false", "no", "off")

Read = Callable[[str], str | None]


@dataclass(frozen=True)
class PaystackSettings:
    """`mode` is what every connector uses unless it has its own; `secret_key` is present only when some
    connector really talks to Paystack."""

    mode: str = "simulated"
    secret_key: str | None = field(default=None, repr=False)
    overrides: Mapping[str, str] = field(default_factory=dict)
    api_url: str = PAYSTACK_API_URL
    """Paystack's address. Only a test rig changes it, and only to this machine (`PAYSTACK_API_URL`)."""

    def mode_for(self, connector: str) -> str:
        return self.overrides.get(connector, self.mode)


@dataclass(frozen=True)
class VtpassSettings:
    mode: str = "simulated"
    credentials: VtpassCredentials | None = None
    debug: bool = False


@dataclass(frozen=True)
class SimulatorSettings:
    transfer_otp: bool = False
    payouts_refused: bool = False
    pending_seconds: int = 20
    food_step_seconds: int = 15
    vtpass_rejects_credentials: bool = False


@dataclass(frozen=True)
class Settings:
    approval_secret: str = field(repr=False)
    per_payment_limit_kobo: int = 5_000_000
    daily_limit_kobo: int = 10_000_000
    group_daily_limit_kobo: int = 50_000_000
    """What the people one outside agent speaks for may approve together in a day (owner.py)."""
    quote_ttl_seconds: int = 600
    checkout_window_seconds: int = 900
    public_base_url: str = "http://localhost:8787"
    payer_email: str = "demo.payer@example.com"
    paystack: PaystackSettings = field(default_factory=PaystackSettings)
    vtpass: VtpassSettings = field(default_factory=VtpassSettings)
    simulator: SimulatorSettings = field(default_factory=SimulatorSettings)
    card_file: str = "card.html"
    alt_cards: tuple[tuple[str, str], ...] = ()
    enable_test_routes: bool = False
    mcp_token: str | None = field(default=None, repr=False)
    card_csp_extra: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    """Origins added to what the approval card declares, to try the host's allowlist with a connector that
    misbehaves (`CARD_CSP_EXTRA`, test routes on only)."""
    mcp_allowed_origins: tuple[str, ...] = ()
    """Browser origins that may call the MCP endpoints (`MCP_ALLOWED_ORIGINS`). None: the callers are servers,
    which send no Origin, and a request that names one is refused (Streamable HTTP, against DNS rebinding)."""
    inline_paystack: bool = True
    """A card may pay in Paystack's popup inside the chat: the approval card asks for the origins the popup
    needs and is given the transaction's access code. Real Paystack test mode only: the simulator has none."""
    require_owner: bool = False
    """A tool call must carry an owner (owner.py); off, a call without one acts for the default owner."""
    host_binding: str | None = None
    host_public_url: str | None = None
    """The chat host's public origin, so the simulated checkout page can link back to the chat."""
    memory: MemorySettings = field(default_factory=MemorySettings)
    web_enabled: bool = True
    """The web tool reads pages (`WEB_ENABLED=0` is the kill switch)."""
    web_deny: tuple[str, ...] = DEFAULT_DENY
    """Sites the web tool refuses, with subdomains (`WEB_DENY`, comma-separated, added to the default)."""

    @classmethod
    def from_env(cls, read: Read) -> Settings:
        env = _Env(read)
        secret = env.text("APPROVAL_SECRET")
        if secret is None:
            raise ConfigError("APPROVAL_SECRET is not set")
        base = cls(approval_secret=secret)
        per_payment = env.positive_int("PER_PAYMENT_LIMIT_KOBO", base.per_payment_limit_kobo)
        daily = env.positive_int("DAILY_LIMIT_KOBO", base.daily_limit_kobo)
        if per_payment > daily:
            raise ConfigError("PER_PAYMENT_LIMIT_KOBO cannot be more than DAILY_LIMIT_KOBO.")
        group_daily = env.positive_int("GROUP_DAILY_LIMIT_KOBO", base.group_daily_limit_kobo)
        if daily > group_daily:
            raise ConfigError("DAILY_LIMIT_KOBO cannot be more than GROUP_DAILY_LIMIT_KOBO.")
        return cls(
            approval_secret=secret,
            per_payment_limit_kobo=per_payment,
            daily_limit_kobo=daily,
            group_daily_limit_kobo=group_daily,
            quote_ttl_seconds=env.positive_int("QUOTE_TTL_SECONDS", base.quote_ttl_seconds),
            checkout_window_seconds=env.positive_int("CHECKOUT_WINDOW_SECONDS", base.checkout_window_seconds),
            public_base_url=env.text("PUBLIC_BASE_URL") or base.public_base_url,
            payer_email=env.text("PAYER_EMAIL") or base.payer_email,
            paystack=_paystack_from(env),
            vtpass=_vtpass_from(env),
            simulator=_simulator_from(env),
            card_file=env.text("CARD_FILE") or base.card_file,
            alt_cards=alt_cards(env.text("ALT_CARDS")),
            enable_test_routes=env.text("ENABLE_TEST_ROUTES") == "1",
            mcp_token=_mcp_token_from(env),
            card_csp_extra=_card_csp_extra_from(env),
            mcp_allowed_origins=tuple(
                o.strip() for o in (env.text("MCP_ALLOWED_ORIGINS") or "").split(",") if o.strip()
            ),
            inline_paystack=env.flag("INLINE_PAYSTACK")
            if env.text("INLINE_PAYSTACK")
            else base.inline_paystack,
            require_owner=env.flag("REQUIRE_OWNER"),
            host_binding=env.text("HOST_BINDING"),
            host_public_url=_origin_from(env, "HOST_PUBLIC_URL"),
            memory=MemorySettings.from_env(read),
            web_enabled=env.text("WEB_ENABLED") != "0",
            web_deny=(*DEFAULT_DENY, *_domains(env.text("WEB_DENY"))),
        )


def _domains(raw: str | None) -> tuple[str, ...]:
    return tuple(d.strip().lower() for d in (raw or "").split(",") if d.strip())


class _Env:
    def __init__(self, read: Read) -> None:
        self._read = read

    def text(self, name: str) -> str | None:
        value = (self._read(name) or "").strip()
        return value or None

    def positive_int(self, name: str, fallback: int) -> int:
        raw = self.text(name)
        if raw is None:
            return fallback
        if not raw.isdecimal() or int(raw) <= 0:
            raise ConfigError(f'{name} must be a positive whole number, got "{raw}".')
        return int(raw)

    def flag(self, name: str) -> bool:
        raw = (self.text(name) or "").lower()
        if raw in _TRUE:
            return True
        if raw in ("", *_FALSE):
            return False
        raise ConfigError(f'{name} must be true or false, got "{raw}".')

    def choice(self, name: str, allowed: tuple[str, ...]) -> str | None:
        raw = (self.text(name) or "").lower()
        if not raw:
            return None
        if raw not in allowed:
            options = " or ".join(f'"{a}"' for a in allowed)
            raise ConfigError(f'{name} must be {options}, got "{raw}".')
        return raw


def alt_cards(spec: str | None) -> tuple[tuple[str, str], ...]:
    """`name=file,...`: extra cards served as ui://paystack-pay/card-<name>.html, to compare card
    implementations against the same server (development only)."""
    pairs = [item.split("=", 1) for item in (spec or "").split(",") if "=" in item]
    return tuple((name.strip(), file.strip()) for name, file in pairs)


MIN_MCP_TOKEN_LENGTH = 32


def _mcp_token_from(env: _Env) -> str | None:
    """The bearer token every MCP call must carry, when there is one. `REQUIRE_MCP_TOKEN` makes a
    missing token a startup failure, so a public deployment never serves the tools without it."""
    token = env.text("MCP_ACCESS_TOKEN")
    if token is None and env.flag("REQUIRE_MCP_TOKEN"):
        raise ConfigError("REQUIRE_MCP_TOKEN is set but MCP_ACCESS_TOKEN is not.")
    if token is not None and len(token) < MIN_MCP_TOKEN_LENGTH:
        raise ConfigError(f"MCP_ACCESS_TOKEN must be at least {MIN_MCP_TOKEN_LENGTH} characters.")
    return token


_LOOPBACK = ("localhost", "127.0.0.1", "[::1]", "::1")


def _origin_from(env: _Env, name: str) -> str | None:
    raw = env.text(name)
    if raw is None:
        return None
    parts = urlsplit(raw)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.path not in ("", "/"):
        raise ConfigError(f'{name} must be an origin such as https://chat.example, got "{raw}".')
    return f"{parts.scheme}://{parts.netloc}"


def _test_key_from(env: _Env) -> str | None:
    for name in _LIVE_KEY_HOLDERS:
        if (env.text(name) or "").startswith("sk_live_"):
            raise ConfigError(
                f"{name} is a live key (sk_live_...). This project only runs with test keys or the "
                "simulator. Remove it."
            )
    key = env.text("PAYSTACK_TEST_SECRET_KEY")
    if key is not None and not _TEST_KEY.fullmatch(key):
        raise ConfigError(
            "PAYSTACK_TEST_SECRET_KEY must be a Paystack test secret key that starts with sk_test_."
        )
    return key


def _paystack_api_from(env: _Env) -> str:
    """Paystack's own address, or, for a test rig that stands in for it, an http address on this machine. No
    other address is accepted, so the key can go nowhere else."""
    raw = env.text("PAYSTACK_API_URL")
    if raw is None:
        return PAYSTACK_API_URL
    parts = urlsplit(raw)
    try:
        here = parts.scheme == "http" and parts.hostname in _LOOPBACK and parts.port is not None
    except ValueError:
        here = False
    plain = parts.path in ("", "/") and not (
        parts.query or parts.fragment or parts.username or parts.password
    )
    if raw != PAYSTACK_API_URL and not (here and plain):
        raise ConfigError(
            "PAYSTACK_API_URL must be https://api.paystack.co or an http address on this machine."
        )
    return raw.rstrip("/")


def _card_csp_extra_from(env: _Env) -> dict[str, tuple[str, ...]]:
    raw = env.text("CARD_CSP_EXTRA")
    if raw is None:
        return {}
    if env.text("ENABLE_TEST_ROUTES") != "1":
        raise ConfigError("CARD_CSP_EXTRA is a test setting: it needs ENABLE_TEST_ROUTES=1.")
    try:
        parsed = json.loads(raw)
        return {str(name): tuple(str(entry) for entry in entries) for name, entries in parsed.items()}
    except (ValueError, AttributeError, TypeError) as error:
        raise ConfigError(
            'CARD_CSP_EXTRA must be JSON such as {"connectDomains": ["https://x.example"]}.'
        ) from error


def _connector_overrides(env: _Env) -> dict[str, str]:
    """ "real" means Paystack test mode; "test" is accepted as the same thing."""
    overrides: dict[str, str] = {}
    for connector, variable in CONNECTOR_MODE_VARIABLES.items():
        raw = (env.text(variable) or "").lower()
        if raw == "simulated":
            overrides[connector] = "simulated"
        elif raw in ("real", "test"):
            overrides[connector] = "test"
        elif raw:
            raise ConfigError(f'{variable} must be "simulated" or "real", got "{raw}".')
    return overrides


def _paystack_from(env: _Env) -> PaystackSettings:
    key = _test_key_from(env)
    mode = env.choice("PAYSTACK_MODE", ("simulated", "test")) or ("simulated" if key is None else "test")
    overrides = _connector_overrides(env)
    any_real = mode == "test" or "test" in overrides.values()
    if any_real and key is None:
        raise ConfigError("Real Paystack test mode needs PAYSTACK_TEST_SECRET_KEY set to an sk_test_ key.")
    return PaystackSettings(mode, key if any_real else None, overrides, _paystack_api_from(env))


def _vtpass_from(env: _Env) -> VtpassSettings:
    api, public, secret = (env.text(n) for n in ("VTPASS_API_KEY", "VTPASS_PUBLIC_KEY", "VTPASS_SECRET_KEY"))
    credentials = VtpassCredentials(api, public, secret) if api and public and secret else None
    mode = env.choice("VTPASS_MODE", ("simulated", "sandbox", "live")) or (
        "sandbox" if credentials else "simulated"
    )
    if mode == "live":
        raise ConfigError(
            "VTPASS_MODE=live is refused: this build talks only to the VTpass sandbox and its simulator, "
            "and no setting reaches live VTpass."
        )
    if mode == "sandbox" and credentials is None:
        raise ConfigError(
            "VTPASS_MODE=sandbox needs VTPASS_API_KEY, VTPASS_PUBLIC_KEY and VTPASS_SECRET_KEY "
            "from a VTpass sandbox account."
        )
    return VtpassSettings(mode, credentials if mode == "sandbox" else None, env.flag("VTPASS_DEBUG"))


def _simulator_from(env: _Env) -> SimulatorSettings:
    return SimulatorSettings(
        transfer_otp=env.flag("SIM_TRANSFER_OTP"),
        payouts_refused=env.flag("SIM_PAYOUTS_REFUSED"),
        pending_seconds=env.positive_int("SIM_PENDING_SECONDS", 20),
        food_step_seconds=env.positive_int("FOOD_STEP_SECONDS", 15),
        vtpass_rejects_credentials=env.flag("SIM_VTPASS_REJECT_CREDENTIALS"),
    )
