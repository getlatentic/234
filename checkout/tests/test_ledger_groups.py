# SPDX-License-Identifier: AGPL-3.0-or-later
"""The people one outside agent speaks for are owners of their own, so each has a daily limit; together they
are a payer group, and the group's approved spend each day is capped across all of them. A quote keeps the
group it was made in, so approving it later, from anywhere, counts against the same group."""

import pytest

from checkout.errors import DomainError
from checkout.ledger import Limits
from checkout.owner import acting_for
from tests.ledger_support import new_quote

GROUP, OTHER_GROUP = "a" * 32, "b" * 32
TEN_THOUSAND = 1_000_000


def person(n: int) -> str:
    return f"{n:032x}"


async def approved(app, owner, group, key, amount=TEN_THOUSAND):
    with acting_for(owner, group):
        quote, _ = await app.ledger.create(new_quote(amount, key))
        return await app.ledger.claim_approval(quote.id, "paystack-pay")


@pytest.fixture
def capped(app):
    app.ledger.limits = Limits(per_payment_kobo=TEN_THOUSAND, daily_kobo=2 * TEN_THOUSAND,
                               group_daily_kobo=3 * TEN_THOUSAND)  # fmt: skip
    return app


async def test_new_people_of_one_agent_cannot_spend_past_the_groups_day(capped):
    for n in range(3):
        assert (await approved(capped, person(n), GROUP, f"key-{n:08d}"))[1] is True
    with pytest.raises(DomainError) as refused, acting_for(person(9), GROUP):
        await capped.ledger.create(new_quote(TEN_THOUSAND, "key-00000009"))
    assert refused.value.code == "LIMIT_GROUP_DAILY"
    assert "the most one agent's people can spend in a day" in refused.value.message


async def test_a_quote_made_before_the_group_filled_is_refused_at_approval(capped):
    with acting_for(person(8), GROUP):
        early, _ = await capped.ledger.create(new_quote(TEN_THOUSAND, "key-early001"))
    for n in range(3):
        await approved(capped, person(n), GROUP, f"key-{n:08d}")
    with pytest.raises(DomainError) as refused, acting_for(person(8)):
        await capped.ledger.claim_approval(early.id, "paystack-pay")
    assert refused.value.code == "LIMIT_GROUP_DAILY", "the quote's own group counts, not the approver's"


async def test_another_group_and_people_in_no_group_are_not_held_by_it(capped):
    for n in range(3):
        await approved(capped, person(n), GROUP, f"key-{n:08d}")
    assert (await approved(capped, person(20), OTHER_GROUP, "key-other001"))[1] is True
    assert (await approved(capped, person(21), "", "key-nogroup1"))[1] is True


async def test_a_group_is_a_key_like_an_owner():
    with pytest.raises(ValueError), acting_for(person(1), "not-a-key"):
        pass


async def test_the_group_comes_from_its_header_over_mcp_and_a_malformed_one_is_refused():
    from checkout.owner import GROUP_HEADER, OWNER_HEADER
    from tests.connector_support import key
    from tests.support import make_stack

    stack = make_stack(group_daily_limit_kobo=10_000_000)
    made = {"name": "create_payment_quote", "arguments": {
        "amount_kobo": 6_000_000 // 2, "amount_as_user_said": "30k", "description": "Lunch",
        "merchant": "Demo Kitchen", "idempotency_key": key("group-mcp")}}  # fmt: skip
    for n in range(4):
        made["arguments"]["idempotency_key"] = key(f"group-{n}")
        answer = await stack.mcp("paystack-pay", "tools/call", made, person(n), headers={GROUP_HEADER: GROUP})
        assert not answer["result"].get("isError"), answer
    rows = await stack.app.ledger._db.rows("SELECT DISTINCT payer_group FROM quotes")
    assert [r["payer_group"] for r in rows] == [GROUP]
    bad = await stack.mcp(
        "paystack-pay", "tools/call", made, headers={OWNER_HEADER: person(1), GROUP_HEADER: "x"}
    )
    assert bad["error"]["message"] == "The group header is not an owner key."


async def test_a_quotes_group_can_never_be_changed(capped):
    with acting_for(person(1), GROUP):
        quote, _ = await capped.ledger.create(new_quote(TEN_THOUSAND, "key-fixed001"))
    with pytest.raises(Exception, match="cannot be changed"):
        await capped.ledger._db.execute("UPDATE quotes SET payer_group = '' WHERE id = ?", quote.id)
