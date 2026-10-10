# SPDX-License-Identifier: AGPL-3.0-or-later
"""Starting a top-up (wallet/topups.py): a signed-in owner's wallet that is not frozen, an amount within the
cap, a Bachs checkout for exactly that amount with the top-up id as its reference; and expiry."""

import pytest

from checkout.errors import DomainError
from checkout.wallet.settings import WalletSettings
from checkout.wallet.topups import TOPUP_MINUTES, owner_tag
from tests.support import ALICE, BOB, make_stack
from tests.topup_support import SECRET, started, state_of, topups


@pytest.fixture
def stack():
    return make_stack(approval_secret=SECRET)


async def test_a_top_up_is_open_with_a_checkout_on_the_simulated_bachs(stack):
    topup = await started(stack, 500_000)
    assert topup.state == "open" and topup.owner == ALICE and topup.amount_kobo == 500_000
    assert topup.id.startswith("wt-") and topup.provider_ref and topup.provider_ref.startswith("chk_")
    assert topup.checkout_url == f"http://localhost:8787/sim/bachs/{topup.provider_ref}"
    assert topup.expires_at == stack.clock.now() + TOPUP_MINUTES * 60_000
    checkout = await stack.app.funding.sim.checkout(topup.provider_ref)
    assert (checkout.reference, checkout.amount, checkout.currency) == (topup.id, "5000.00", "NGN")
    assert checkout.metadata == {"wallet_topup": topup.id, "wallet_owner": owner_tag(ALICE)}


async def test_the_owner_key_never_goes_to_bachs(stack):
    topup = await started(stack)
    checkout = await stack.app.funding.sim.checkout(topup.provider_ref)
    assert ALICE not in str(checkout)


async def test_a_visitor_has_no_wallet_and_cannot_top_up(stack):
    with pytest.raises(DomainError) as refused:
        await topups(stack).start(BOB, 100_000)
    assert refused.value.code == "WALLET_NONE"
    assert await stack.count("wallet_topup") == 0


async def test_a_frozen_wallet_cannot_top_up(stack):
    await topups(stack).journal.open(ALICE)
    await topups(stack).journal.set_frozen(ALICE, True)
    with pytest.raises(DomainError) as refused:
        await topups(stack).start(ALICE, 100_000)
    assert refused.value.code == "WALLET_FROZEN"
    assert await stack.count("wallet_topup") == 0


async def test_a_top_up_must_fit_under_the_cap_with_what_the_wallet_holds():
    stack = make_stack(approval_secret=SECRET, wallet=WalletSettings(balance_cap_kobo=1_000_000))
    journal = topups(stack).journal
    await journal.credit(ALICE, "fund", 700_000, "earlier")
    assert (await topups(stack).start(ALICE, 300_000)).state == "open"
    with pytest.raises(DomainError) as refused:
        await topups(stack).start(ALICE, 300_001)
    assert refused.value.code == "WALLET_CAP" and "₦3,000" in refused.value.message
    assert await stack.count("wallet_topup") == 1


@pytest.mark.parametrize("amount", [0, -100, 1.5, True, "500"])
async def test_a_top_up_is_a_positive_whole_number_of_kobo(stack, amount):
    await topups(stack).journal.open(ALICE)
    with pytest.raises(DomainError) as refused:
        await topups(stack).start(ALICE, amount)
    assert refused.value.code == "INVALID_INPUT"
    assert await stack.count("wallet_topup") == 0


async def test_each_top_up_is_its_own_checkout(stack):
    first, second = await started(stack), await started(stack)
    assert first.id != second.id and first.provider_ref != second.provider_ref


async def test_an_open_top_up_expires_with_its_checkout_on_the_minute(stack):
    topup = await started(stack)
    stack.clock.advance(TOPUP_MINUTES * 60 - 1)
    await stack.app.background.minute()
    assert await state_of(stack, topup) == "open"
    stack.clock.advance(1)
    await stack.app.background.minute()
    assert await state_of(stack, topup) == "expired"
    assert await topups(stack).expire_due() == 0
