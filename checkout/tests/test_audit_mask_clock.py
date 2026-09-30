# SPDX-License-Identifier: AGPL-3.0-or-later
import json

from checkout.audit import Audit, scrub
from checkout.clock import format_lagos, lagos_day_start, lagos_stamp
from checkout.mask import group_phone, mask_account, mask_phone
from tests.keys import fake_key
from tests.support import START, FakeClock


def capture():
    lines: list[str] = []
    return Audit([lines.append], FakeClock()), lines


def test_the_audit_log_writes_one_json_line_per_event_with_a_timestamp():
    audit, lines = capture()
    audit.log("quote.created", quote="qt-abc", amount_kobo=50_000)
    assert [json.loads(line) for line in lines] == [
        {"ts": "2026-09-29T10:00:00.000Z", "event": "quote.created", "quote": "qt-abc", "amount_kobo": 50_000}
    ]


def test_a_full_phone_number_passed_by_mistake_is_masked():
    audit, lines = capture()
    audit.log("quote.created", note="for 08031234567 please")
    assert "08031234567" not in lines[0]
    assert "0803****567" in lines[0]


def test_paystack_and_vtpass_keys_are_removed():
    audit, lines = capture()
    audit.log("tool.error", message=f"bad key {fake_key('test')} and SK_abcdef123456")
    assert "abcdefgh12345678" not in lines[0]
    assert "abcdef123456" not in lines[0]
    assert "[redacted-key]" in lines[0]


def test_quote_ids_and_amounts_are_left_alone():
    assert scrub("qt-0123456789abcdef0123") == "qt-0123456789abcdef0123"


def test_fields_left_out_are_not_logged():
    audit, lines = capture()
    audit.log("startup", a=None)
    assert "a" not in json.loads(lines[0])


def test_masking():
    assert mask_phone("08031234567") == "0803****567"
    assert mask_phone("201000000000") == "2010*****000"
    assert mask_phone("12345") == "***45"
    assert mask_account("0123456789") == "******6789"
    assert group_phone("08031234567") == "0803 123 4567"
    assert group_phone("201000000000") == "201000000000"


def test_lagos_time():
    from datetime import UTC, datetime

    def at(*args: int) -> int:
        return int(datetime(*args, tzinfo=UTC).timestamp() * 1000)

    assert lagos_stamp(at(2026, 9, 29, 13, 5)) == "202609291405"
    assert lagos_stamp(at(2026, 9, 29, 23, 30)) == "202609300030"
    assert lagos_day_start(at(2026, 9, 29, 13, 5)) == at(2026, 9, 28, 23)
    assert lagos_day_start(at(2026, 9, 29, 23, 30)) == at(2026, 9, 29, 23)
    assert format_lagos(at(2026, 9, 29, 10, 5)) == "29 Sep 2026, 11:05 WAT"
    assert lagos_stamp(START) == "202609291100"
