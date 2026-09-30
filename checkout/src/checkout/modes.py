# SPDX-License-Identifier: AGPL-3.0-or-later
"""One plain sentence that says what kind of money, if any, a connector moves."""

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Modes:
    paystack: str
    vtpass: str | None = None
    merchant: str | None = None
    """Set when the connector's merchant is invented, for example "Simulated merchant: not Chowdeck"."""
    reason: str | None = None
    """Why this connector simulates while the rest are real, when the owner chose that."""

    def as_dict(self) -> dict[str, str]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass(frozen=True)
class ModeInfo:
    label: str
    simulated: bool


def _payment_label(modes: Modes) -> ModeInfo:
    parts = ["Simulated Paystack" if modes.paystack == "simulated" else "Paystack test mode"]
    if modes.vtpass:
        parts.append("Simulated VTpass" if modes.vtpass == "simulated" else "VTpass sandbox")
    every_simulated = modes.paystack == "simulated" and (modes.vtpass or "simulated") == "simulated"
    simulated = modes.paystack == "simulated" or modes.vtpass == "simulated"
    if every_simulated:
        reason = f" ({modes.reason})" if modes.reason else ""
        return ModeInfo(f"Simulated: no money moves{reason}", simulated)
    nothing_sent = ", no airtime is sent" if modes.vtpass == "sandbox" else ""
    return ModeInfo(f"{' + '.join(parts)}: no real money moves{nothing_sent}", simulated)


def describe_mode(modes: Modes) -> ModeInfo:
    payment = _payment_label(modes)
    if not modes.merchant:
        return payment
    return ModeInfo(f"{modes.merchant} · {payment.label}", True)
