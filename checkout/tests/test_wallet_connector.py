# SPDX-License-Identifier: AGPL-3.0-or-later
"""The wallet connector through its HTTP surface, as the host calls it (connectors/wallet.py): one model
tool that reads, two the card calls, an account's own wallet opened the first time it asks, and nothing at
all for a visitor."""

from checkout.wallet.journal import Journal
from checkout.wallet.settings import WalletSettings
from tests.connector_support import listed, text_of, visibility
from tests.support import ALICE, BOB, make_stack
from tests.wallet_card_support import CARD_ID, ok, pay_on_stand_in, wallet, wallets


def journal(stack) -> Journal:
    return stack.app.funding.topups.journal


class TestWhatAHostSees:
    async def test_the_model_has_one_tool_and_it_only_reads(self, stack):
        tools = await listed(stack, "wallet")
        assert {name: visibility(tool) for name, tool in tools.items()} == {
            "wallet_balance": ["model"],
            "wallet_view": ["app"],
            "start_topup": ["app"],
            "start_withdrawal": ["app"],
            "withdraw": ["app"],
        }
        assert tools["wallet_balance"]["annotations"]["readOnlyHint"] is True
        assert tools["wallet_balance"]["inputSchema"].get("properties", {}) == {}
        assert {t["_meta"]["ui"]["resourceUri"] for t in tools.values()} == {"ui://wallet/card.html"}

    async def test_the_card_is_served(self, stack):
        read = await stack.mcp("wallet", "resources/read", {"uri": "ui://wallet/card.html"})
        assert "<title>Wallet</title>" in read["result"]["contents"][0]["text"]


class TestAccountsOnly:
    async def test_a_call_without_an_account_is_refused_before_any_tool_runs(self, stack):
        for tool, args in (
            ("wallet_balance", {}),
            ("wallet_view", {"card_id": CARD_ID}),
            ("start_topup", {"card_id": CARD_ID, "amount_naira": 1000}),
        ):
            refused = await wallet(stack, tool, account=False, **args)
            assert refused["error"]["message"] == "Wallet is for signed-in accounts."
        assert await wallets(stack) == 0 and await stack.count("wallet_topup") == 0

    async def test_an_account_header_for_someone_else_reaches_no_wallet(self, stack):
        answer = await stack.mcp(
            "wallet",
            "tools/call",
            {"name": "wallet_balance", "arguments": {}},
            ALICE,
            {"x-memory-owner": BOB},
        )
        assert text_of(answer["result"]).startswith("WALLET_ACCOUNT_ONLY")
        assert await wallets(stack) == 0


class TestTheBalance:
    async def test_the_wallet_is_opened_the_first_time_an_account_asks_and_once(self, stack):
        assert await wallets(stack) == 0
        first = ok(await wallet(stack, "wallet_balance"))
        ok(await wallet(stack, "wallet_balance"))
        assert await wallets(stack) == 1
        assert text_of(first) == "The wallet holds ₦0."
        data = first["structuredContent"]
        assert len(data["card_id"]) == 32 and data["wallet"]["balanceKobo"] == 0
        assert data["wallet"]["entries"] == [] and data["wallet"]["frozen"] is False

    async def test_each_balance_is_a_card_of_its_own(self, stack):
        one = ok(await wallet(stack, "wallet_balance"))["structuredContent"]["card_id"]
        two = ok(await wallet(stack, "wallet_balance"))["structuredContent"]["card_id"]
        assert one != two

    async def test_the_view_says_each_entry_in_plain_words_newest_first(self, stack):
        await journal(stack).credit(ALICE, "fund", 300_000, "top-up-1")
        await journal(stack).debit(ALICE, "spend", 50_000, "q-1")
        await journal(stack).credit(ALICE, "release", 50_000, "q-1")
        view = ok(await wallet(stack, "wallet_view", card_id=CARD_ID))["structuredContent"]
        assert view["card_id"] == CARD_ID and view["wallet"]["balance"] == "₦3,000"
        lines = [(e["label"], e["amount"]) for e in view["wallet"]["entries"]]
        assert lines == [("Returned", "+₦500"), ("Paid", "-₦500"), ("Added", "+₦3,000")]

    async def test_one_account_never_sees_anothers_wallet(self, stack):
        await journal(stack).open(BOB)
        await journal(stack).credit(BOB, "fund", 300_000, "top-up-1")
        view = ok(await wallet(stack, "wallet_view", card_id=CARD_ID))["structuredContent"]["wallet"]
        assert view["balanceKobo"] == 0 and view["entries"] == []


class TestAddingMoney:
    async def test_a_top_up_gives_the_card_a_checkout_and_paying_it_adds_the_money(self, stack):
        started = ok(await wallet(stack, "start_topup", card_id=CARD_ID, amount_naira=2500))
        topup = started["structuredContent"]["topup"]
        assert topup["amountKobo"] == 250_000 and "/sim/bachs/" in topup["checkoutUrl"]
        assert text_of(started) == "Adding ₦2,500: pay on the checkout."
        assert started["structuredContent"]["wallet"]["balanceKobo"] == 0
        await pay_on_stand_in(stack, topup["checkoutUrl"])
        view = ok(await wallet(stack, "wallet_view", card_id=CARD_ID))["structuredContent"]["wallet"]
        assert view["balance"] == "₦2,500" and view["entries"][0]["label"] == "Added"

    async def test_a_top_up_opens_the_wallet_of_an_account_that_never_asked(self, stack):
        ok(await wallet(stack, "start_topup", card_id=CARD_ID, amount_naira=100))
        assert await wallets(stack) == 1

    async def test_the_cap_and_the_freeze_are_the_top_ups_own(self, stack):
        stack = make_stack(wallet=WalletSettings(balance_cap_kobo=100_000))
        refused = await wallet(stack, "start_topup", card_id=CARD_ID, amount_naira=1001)
        assert text_of(refused).startswith("WALLET_CAP")
        await journal(stack).set_frozen(ALICE, True)
        frozen = await wallet(stack, "start_topup", card_id=CARD_ID, amount_naira=100)
        assert text_of(frozen).startswith("WALLET_FROZEN")
        assert await stack.count("wallet_topup") == 0

    async def test_an_amount_is_whole_naira_within_bounds(self, stack):
        for amount in (99, 1_000_001, 10.5):
            refused = await wallet(stack, "start_topup", card_id=CARD_ID, amount_naira=amount)
            assert refused["isError"] is True
        assert await stack.count("wallet_topup") == 0
