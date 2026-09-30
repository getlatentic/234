# SPDX-License-Identifier: AGPL-3.0-or-later
"""Where a quote is in its life as a person on the card would name it, and what kind of money a connector
moves. Ported from the TypeScript demo's phase.test.ts and mode.test.ts."""

import pytest

from checkout.ledger import Quote
from checkout.modes import Modes, describe_mode
from checkout.present import WAITING, phase_of


def quote(state: str, kind: str = "payment", **progress) -> Quote:
    return Quote(
        id="qt-1", connector="paystack-pay", kind=kind, amount_kobo=100, description="x", merchant="m",
        merchant_ref=None, details={"kind": kind}, progress=progress, state=state, created_at=0,
        expires_at=1, approved_at=None, settled_at=None,
    )  # fmt: skip


@pytest.mark.parametrize(
    ("state", "phase"),
    [
        ("open", "awaiting_approval"),
        ("settled", "succeeded"),
        ("failed", "failed"),
        ("abandoned", "abandoned"),
        ("expired", "expired"),
        ("declined", "declined"),
        ("unavailable", "unavailable"),
        ("refund_due", "attention"),
    ],
)
def test_names_a_state_as_a_phase(state, phase):
    assert phase_of(quote(state)) == phase


def test_waits_on_the_checkout_once_the_link_exists_and_before_it_does_just_processes():
    assert phase_of(quote("approved")) == "processing"
    assert phase_of(quote("approved", checkoutUrl="https://x")) == "awaiting_checkout"


def test_is_processing_after_payment_while_airtime_is_being_delivered():
    assert (
        phase_of(quote("approved", "airtime", checkoutUrl="https://x", paymentStatus="success"))
        == "processing"
    )


def test_asks_for_the_otp_on_a_transfer_that_needs_one_and_otherwise_processes():
    assert phase_of(quote("approved", "transfer", transferStatus="otp")) == "awaiting_otp"
    assert phase_of(quote("approved", "transfer", transferStatus="pending")) == "processing"
    assert phase_of(quote("approved", "transfer")) == "processing"


def test_polls_only_while_something_is_in_flight():
    assert set(WAITING) == {"awaiting_checkout", "processing"}


def test_says_plainly_when_everything_is_simulated():
    assert describe_mode(Modes("simulated")).label == "Simulated: no money moves"
    assert describe_mode(Modes("simulated", "simulated")).simulated is True


def test_names_paystack_test_mode():
    mode = describe_mode(Modes("test"))
    assert (mode.label, mode.simulated) == ("Paystack test mode: no real money moves", False)


def test_names_each_real_part_and_each_simulated_part_when_they_are_mixed():
    mixed = describe_mode(Modes("test", "simulated"))
    assert (mixed.label, mixed.simulated) == (
        "Paystack test mode + Simulated VTpass: no real money moves",
        True,
    )
    assert (
        describe_mode(Modes("simulated", "sandbox")).label
        == "Simulated Paystack + VTpass sandbox: no real money moves, no airtime is sent"
    )
    assert describe_mode(Modes("test", "sandbox")).simulated is False


def test_gives_the_reason_when_the_owner_set_a_connector_to_simulate_beside_a_real_account():
    label = describe_mode(Modes("simulated", reason="this Paystack account cannot make payouts")).label
    assert label == "Simulated: no money moves (this Paystack account cannot make payouts)"


def test_does_not_give_a_reason_for_a_connector_that_is_real():
    assert describe_mode(Modes("test", reason="x")).label == "Paystack test mode: no real money moves"


def test_names_an_invented_merchant_first_and_always_counts_as_simulated():
    chowdeck = "Simulated merchant: not Chowdeck"
    real = describe_mode(Modes("test", merchant=chowdeck))
    assert (real.label, real.simulated) == (f"{chowdeck} · Paystack test mode: no real money moves", True)
    assert (
        describe_mode(Modes("simulated", merchant=chowdeck)).label
        == f"{chowdeck} · Simulated: no money moves"
    )
