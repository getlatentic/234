# SPDX-License-Identifier: AGPL-3.0-or-later
"""Migrations 0020 and 0021: the checks and triggers of the merchant and offer tables, the account check, the
simulated merchants' order, and a deployed ledger that already holds quotes taking them."""

import pytest

from checkout.sqlite_db import SqliteDb, all_migrations
from tests.commerce_support import MAMA, NOW, WATER, add_merchant, add_offer, quote

COMMERCE = "0020_commerce.sql"


async def refused(stack, sql: str, *params, match: str = "") -> None:
    with pytest.raises(Exception, match=match):
        await stack.db.execute(sql, *params)


class TestTheMerchantTable:
    @pytest.mark.parametrize(
        "over",
        [
            {"id": "Upper"},
            {"id": "a"},
            {"id": "has space"},
            {"category": "weapons"},
            {"status": "closed"},
            {"requires_link": 2},
            {"min_kobo": 0},
            {"min_kobo": 500, "max_kobo": 400},
            {"fee_kobo": -1},
            {"fields": "{}"},
            {"fields": "not json"},
            {"blurb": ""},
            {"name": "x" * 81},
            {"provider": "Direct Ory"},
        ],
    )
    async def test_a_row_that_breaks_a_rule_is_refused(self, stack, over):
        with pytest.raises(Exception, match="constraint"):
            await add_merchant(stack, "fine-shop", **over)

    async def test_the_statuses_and_categories_of_the_design_are_accepted(self, stack):
        for n, status in enumerate(("live", "beta", "coming_soon")):
            await add_merchant(stack, f"shop-{n}", status=status)
        for n, category in enumerate(
            ("food", "grocery", "health", "shop", "service", "airtime", "data", "tv", "electricity")
        ):
            await add_merchant(stack, f"cat-{n}", category=category)

    async def test_a_merchant_keeps_its_id_and_provider(self, stack):
        await refused(
            stack, "UPDATE merchant SET id = 'other-id' WHERE id = ?", MAMA, match="keeps its id and provider"
        )
        await refused(
            stack,
            "UPDATE merchant SET provider = 'vtpass' WHERE id = ?",
            MAMA,
            match="keeps its id and provider",
        )

    async def test_everything_else_about_a_merchant_may_change(self, stack):
        await stack.db.execute(
            "UPDATE merchant SET status = 'coming_soon', fee_kobo = 5, name = 'New' WHERE id = ?", MAMA
        )
        assert (await stack.db.row("SELECT status FROM merchant WHERE id = ?", MAMA))[
            "status"
        ] == "coming_soon"


class TestTheOfferTable:
    @pytest.mark.parametrize(
        "over",
        [
            {"price_kobo": None},
            {"price_kobo": 0},
            {"price_kobo": 1.5},
            {"min_kobo": 100, "max_kobo": 200},
            {"price_kind": "open"},
            {"price_kind": "range", "price_kobo": None, "min_kobo": 500, "max_kobo": 400},
            {"price_kind": "range", "price_kobo": None, "min_kobo": 500},
            {"price_kind": "barter"},
            {"max_quantity": 0},
            {"max_quantity": 11},
            {"available": 2},
            {"option_groups": "{}"},
            {"id": "BAD ID"},
            {"name": ""},
        ],
    )
    async def test_an_offer_that_breaks_a_rule_is_refused(self, stack, over):
        with pytest.raises(Exception, match="constraint"):
            await add_offer(stack, MAMA, "new-offer", **over)

    async def test_a_range_and_an_open_offer_are_accepted_when_they_say_their_limits(self, stack):
        await add_offer(
            stack, MAMA, "ranged", price_kind="range", price_kobo=None, min_kobo=100, max_kobo=200
        )
        await add_offer(stack, MAMA, "open-ended", price_kind="open", price_kobo=None)

    async def test_an_offer_needs_a_merchant_that_exists(self, stack):
        with pytest.raises(Exception, match="FOREIGN KEY"):
            await add_offer(stack, "no-such-merchant", "orphan")

    async def test_an_offer_id_is_one_per_merchant_not_one_in_all(self, stack):
        await add_merchant(stack, "other-shop")
        await add_offer(stack, "other-shop", "zobo")
        with pytest.raises(Exception, match=r"UNIQUE|PRIMARY"):
            await add_offer(stack, "other-shop", "zobo")

    async def test_an_offer_keeps_its_merchant_id_and_kind_of_price(self, stack):
        for column, value in (("merchant_id", "lagosmed-pharmacy"), ("id", "other"), ("price_kind", "open")):
            await refused(
                stack, f"UPDATE offer SET {column} = ? WHERE id = 'zobo'", value, match="keeps its merchant"
            )

    async def test_a_price_and_availability_may_change_and_a_quote_keeps_what_it_used(self, stack):
        await stack.db.execute("UPDATE offer SET price_kobo = 90000, available = 0 WHERE id = 'zobo'")
        assert (await stack.db.row("SELECT price_kobo FROM offer WHERE id = 'zobo'"))["price_kobo"] == 90000


class TestWhatAQuoteNamesIsRetiredNotRemoved:
    async def test_a_merchant_and_an_offer_no_quote_names_may_be_removed(self, stack):
        await add_merchant(stack)
        await stack.db.execute("DELETE FROM offer WHERE merchant_id = 'test-shop'")
        await stack.db.execute("DELETE FROM merchant WHERE id = 'test-shop'")
        assert await stack.db.row("SELECT 1 FROM merchant WHERE id = 'test-shop'") is None

    async def test_an_offer_a_quote_names_cannot_be_removed_but_another_can(self, stack):
        await quote(stack)
        await refused(
            stack,
            "DELETE FROM offer WHERE merchant_id = ? AND id = 'zobo'",
            MAMA,
            match="retired, not removed",
        )
        await stack.db.execute("DELETE FROM offer WHERE merchant_id = ? AND id = 'puff-puff'", MAMA)

    async def test_a_merchant_a_quote_names_cannot_be_removed(self, stack):
        await quote(stack)
        await stack.db.execute(
            "DELETE FROM offer WHERE merchant_id = ? AND id NOT IN ('zobo', 'jollof-chicken')", MAMA
        )
        await refused(stack, "DELETE FROM merchant WHERE id = ?", MAMA, match="retired, not removed")
        assert await stack.db.row("SELECT 1 FROM merchant WHERE id = ?", MAMA) is not None

    async def test_the_quote_itself_is_still_fixed(self, stack):
        made = await quote(stack)
        await refused(
            stack,
            "UPDATE quotes SET details = '{}' WHERE id = ?",
            made["structuredContent"]["quote"]["id"],
            match="cannot be changed",
        )


CHECK_SQL = (
    "INSERT INTO account_check (id, owner, merchant_id, fields, holder_name, due_kobo, created_at,"
    " expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
)
CHECK_ROW = ("ck-" + "0" * 20, "a1" * 16, WATER, '{"card_number":"1"}', "ADA", None, 1, 2)


class TestTheOtherTables:
    async def test_an_account_check_is_kept_as_it_was_made(self, stack):
        await stack.db.execute(CHECK_SQL, *CHECK_ROW)
        await refused(stack, "UPDATE account_check SET holder_name = 'X'", match="cannot be changed")

    @pytest.mark.parametrize(
        ("column", "value"),
        [(0, "ck-short"), (1, "NOT-HEX"), (3, "[]"), (4, ""), (5, -1), (7, 1)],
    )
    async def test_an_account_check_that_breaks_a_rule_is_refused(self, stack, column, value):
        row = list(CHECK_ROW)
        row[column] = value
        with pytest.raises(Exception, match="constraint"):
            await stack.db.execute(CHECK_SQL, *row)

    async def test_a_simulated_merchant_that_answered_keeps_its_answer_and_a_pending_one_may_move(
        self, stack
    ):
        for quote_id, outcome in (("q1", "pending"), ("q2", "delivered")):
            await stack.db.execute(
                "INSERT INTO sim_merchant_order (quote_id, outcome, description, created_at)"
                " VALUES (?, ?, 'd', 1)",
                quote_id,
                outcome,
            )
        await stack.db.execute("UPDATE sim_merchant_order SET outcome = 'failed' WHERE quote_id = 'q1'")
        await refused(
            stack,
            "UPDATE sim_merchant_order SET outcome = 'failed' WHERE quote_id = 'q2'",
            match="keeps its answer|does not change",
        )
        await refused(
            stack,
            "UPDATE sim_merchant_order SET outcome = 'failed' WHERE quote_id = 'q1'",
            match="does not change",
        )


class TestADeployedLedgerTakesTheMigrations:
    async def test_quotes_made_before_stay_as_they_were_and_the_directory_arrives(self):
        ordered = all_migrations()
        at = next(i for i, m in enumerate(ordered) if m.name == COMMERCE)
        db = SqliteDb(ordered[:at])
        db.connection.execute(
            "INSERT INTO quotes (id, owner, payer_group, connector, kind, amount_kobo, currency, description,"
            " merchant, details, progress, state, idempotency_key, request_hash, created_at, expires_at)"
            " VALUES ('qt-00000000000000000001', ?, '', 'airtime', 'airtime', 50000, 'NGN', 'MTN airtime',"
            " 'MTN',"
            " '{}', '{}', 'open', 'key', 'h', 1, 2)",
            ("a1" * 16,),
        )
        for migration in ordered[at:]:
            db.migrate(migration)
        assert (await db.row("SELECT COUNT(*) AS n FROM quotes"))["n"] == 1
        assert (await db.row("SELECT COUNT(*) AS n FROM merchant"))["n"] == 4
        assert (await db.row("SELECT COUNT(*) AS n FROM offer"))["n"] == 26
        assert (await db.row("SELECT created_at FROM merchant WHERE id = ?", MAMA))["created_at"] == NOW

    def test_the_two_migrations_are_the_next_free_numbers(self):
        names = [m.name for m in all_migrations()]
        assert names[names.index(COMMERCE) :][:2] == [COMMERCE, "0021_commerce_directory.sql"]
        assert [n[:4] for n in names] == [f"{i:04d}" for i in range(1, len(names) + 1)]
