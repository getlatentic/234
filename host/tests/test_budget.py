# SPDX-License-Identifier: AGPL-3.0-or-later
import asyncio

from turns.budget import GLOBAL_SCOPE, day_of, take_model_call

AT = 1_790_000_000_000


async def used(sql, scope):
    row = await sql.row("SELECT used FROM chat_budget WHERE scope = ? AND day = ?", scope, day_of(AT))
    return row["used"] if row else 0


async def test_a_cap_allows_exactly_its_calls(sql):
    verdicts = [await take_model_call(sql, "v:a", AT, 0, 3) for _ in range(5)]
    assert verdicts == [None, None, None, "global", "global"]
    assert await used(sql, GLOBAL_SCOPE) == 3


async def test_a_cap_of_zero_is_no_cap(sql):
    verdicts = [await take_model_call(sql, "v:a", AT, 0, 0) for _ in range(5)]
    assert verdicts == [None] * 5


async def test_each_visitor_has_their_own_share_and_the_global_cap_is_still_shared(sql):
    assert [await take_model_call(sql, "v:a", AT, 2, 3) for _ in range(3)] == [None, None, "visitor"]
    assert await take_model_call(sql, "v:b", AT, 2, 3) is None
    assert await take_model_call(sql, "v:b", AT, 2, 3) == "global"
    assert await used(sql, GLOBAL_SCOPE) == 3


async def test_a_refusal_by_the_global_cap_gives_the_visitors_call_back(sql):
    await take_model_call(sql, "v:a", AT, 5, 1)
    assert await take_model_call(sql, "v:b", AT, 5, 1) == "global"
    assert await used(sql, "v:b") == 0


async def test_the_cap_starts_again_the_next_day(sql):
    await take_model_call(sql, "v:a", AT, 1, 1)
    assert await take_model_call(sql, "v:a", AT + 24 * 3600 * 1000, 1, 1) is None


async def test_calls_that_arrive_together_still_stop_at_the_cap(sql):
    verdicts = await asyncio.gather(*[take_model_call(sql, "v:a", AT, 0, 4) for _ in range(9)])
    assert verdicts.count(None) == 4


async def test_a_token_cap_is_read_before_a_round_and_a_rounds_tokens_are_added_after_it(sql):
    from turns.budget import add_tokens, tokens_used_up

    assert await tokens_used_up(sql, "v:a", AT, 1000, 5000) is None
    await add_tokens(sql, "v:a", AT, 600, 1000, 5000)
    assert await tokens_used_up(sql, "v:a", AT, 1000, 5000) is None
    await add_tokens(sql, "v:a", AT, 500, 1000, 5000)
    assert await tokens_used_up(sql, "v:a", AT, 1000, 5000) == "visitor", "1,100 is over 1,000"
    assert await tokens_used_up(sql, "v:b", AT, 1000, 5000) is None, "someone else has their own share"


async def test_the_global_token_cap_is_shared_and_a_cap_of_zero_is_none(sql):
    from turns.budget import add_tokens, tokens_used_up

    await add_tokens(sql, "v:a", AT, 3000, 0, 5000)
    await add_tokens(sql, "v:b", AT, 2500, 0, 5000)
    assert await tokens_used_up(sql, "v:c", AT, 0, 5000) == "global"
    assert await tokens_used_up(sql, "v:c", AT, 0, 0) is None
    assert await used(sql, "tokens:v:a") == 0, "no per-visitor cap, nothing counted for them"
    assert await used(sql, "tokens:global") == 5500


async def test_a_new_day_starts_the_count_again(sql):
    from turns.budget import add_tokens, tokens_used_up

    await add_tokens(sql, "v:a", AT, 5000, 1000, 1000)
    assert await tokens_used_up(sql, "v:a", AT, 1000, 1000) is not None
    assert await tokens_used_up(sql, "v:a", AT + 24 * 3600 * 1000, 1000, 1000) is None


async def test_adding_nothing_changes_nothing(sql):
    from turns.budget import add_tokens

    await add_tokens(sql, "v:a", AT, 0, 1000, 1000)
    assert await used(sql, "tokens:v:a") == 0
