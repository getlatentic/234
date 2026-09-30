# SPDX-License-Identifier: AGPL-3.0-or-later
from pathlib import Path

from chat.starters import MAX_LENGTH, STARTERS
from turns.inputs import clean_text

ICONS = Path(__file__).resolve().parent.parent / "src" / "chat" / "templates" / "chat" / "icons"
FILLS = [s for s in STARTERS if not s.sends]
SENDS = [s for s in STARTERS if s.sends]


def test_there_are_four_to_six_starters_of_one_short_line_each():
    assert 4 <= len(STARTERS) <= 6
    assert all(0 < len(s.label) <= MAX_LENGTH for s in STARTERS)
    assert len({s.label for s in STARTERS}) == len(STARTERS)


def test_a_starter_that_sends_is_a_message_the_host_accepts_word_for_word():
    assert SENDS
    for starter in SENDS:
        assert starter.text == starter.label
        assert clean_text(starter.text) == starter.text


def test_a_starter_that_lacks_something_only_the_person_knows_is_a_beginning_to_finish():
    assert {s.icon for s in FILLS} == {"airtime", "data", "transfer"}
    for starter in FILLS:
        assert starter.text.endswith(" ") and starter.text != starter.label
        assert clean_text(starter.text + "08031234567") == starter.text + "08031234567"


def test_a_starter_that_sends_has_nothing_left_to_finish():
    for starter in SENDS:
        assert not starter.text.endswith(" ")


def test_each_starter_has_its_own_drawn_icon_in_the_menu_tiles_language():
    assert len({s.icon for s in STARTERS}) == len(STARTERS)
    for starter in STARTERS:
        svg = (ICONS / f"{starter.icon}.html").read_text()
        assert svg.startswith("<svg") and 'viewBox="0 0 48 48"' in svg and 'stroke-linecap="round"' in svg
        assert 'fill="currentColor" fill-opacity=".2"' in svg or starter.icon == "data"
        assert 'aria-hidden="true"' in svg


def test_the_starters_cover_airtime_data_a_transfer_food_and_paying_a_merchant():
    text = " ".join(s.label for s in STARTERS).lower()
    for word in ("airtime", "data", "send", "order", "pay"):
        assert word in text
