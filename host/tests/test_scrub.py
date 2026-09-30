# SPDX-License-Identifier: AGPL-3.0-or-later
import pytest

from turns.compaction.scrub import CARD_REMOVED, LINK_REMOVED, REMOVED, scrubbed

TOKEN = "9f2c" * 16


@pytest.mark.parametrize(
    ("text", "gone"),
    [
        ("pay at https://checkout.paystack.com/abc123 now", "checkout.paystack.com"),
        ("see www.example.com/pay?x=1", "example.com"),
        (f"approval token: {TOKEN}", TOKEN),
        (f'{{"approvalToken": "{TOKEN}"}}', TOKEN),
        (f"the code is {TOKEN}", TOKEN),
        ("sk_live_abcdefghijklmnop1234", "abcdefghijklmnop1234"),
        ("pk_test_abcdefghijklmnop1234", "abcdefghijklmnop1234"),
        ("Authorization: Bearer abcdefghijklmnopqrstuvwxyz", "abcdefghijklmnopqrstuvwxyz"),
        ("access_code: 0peioxfhpn", "0peioxfhpn"),
        ("api key = hunter2hunter2", "hunter2hunter2"),
        ("Your one-time code is 123456", "123456"),
        ("my card is 4242 4242 4242 4242", "4242 4242 4242 4242"),
    ],
)
def test_what_must_never_be_remembered_is_taken_out(text, gone):
    assert gone not in scrubbed(text)


@pytest.mark.parametrize(
    "text",
    [
        "Buy ₦5,000 MTN airtime for 07031234567",
        "Send 5k to Ada, GTBank 0123456789",
        "Quote qt-0123456789abcdef0123 is awaiting approval",
        "I have a secret admirer and no password habits",
        "Ẹ kú àárọ̀, mo fẹ́ ra airtime",
        "the pin is not shown here",
    ],
)
def test_what_a_person_says_about_money_is_kept(text):
    assert scrubbed(text) == text


def test_each_kind_leaves_its_own_mark():
    assert LINK_REMOVED in scrubbed("go to https://x.example/a")
    assert REMOVED in scrubbed(f"token={TOKEN}")
    assert CARD_REMOVED in scrubbed("4242424242424242")
