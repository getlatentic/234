# SPDX-License-Identifier: AGPL-3.0-or-later
"""Reading VTpass replies, ported from the TypeScript demo's interpret.test.ts."""

import pytest

from checkout.vtpass.api import VtpassOutcome
from checkout.vtpass.interpret import interpret_vtpass, no_confirmation


def processed(status: str) -> dict:
    return {
        "code": "000",
        "response_description": "TRANSACTION SUCCESSFUL",
        "content": {"transactions": {"status": status}},
    }


class TestRepliesTheRealSandboxSent:
    """Observed on 2026-09-29."""

    def test_http_401_with_the_plain_string_is_refused_never_pending(self):
        assert interpret_vtpass("Invalid Credentials.", 401) == VtpassOutcome(
            "failed", "401", "VTpass refused the credentials (HTTP 401). The order was not placed.", False
        )

    def test_http_401_with_code_087_and_a_message_field_is_refused_using_the_message(self):
        assert interpret_vtpass({"code": "087", "message": "INVALID CREDENTIALS"}, 401).status == "failed"
        assert interpret_vtpass({"code": "087", "message": "INVALID CREDENTIALS"}) == VtpassOutcome(
            "failed", "087", "INVALID CREDENTIALS", False
        )

    def test_http_403_is_refused_too(self):
        assert interpret_vtpass({}, 403).status == "failed"

    def test_a_200_with_an_unreadable_body_does_not_count_as_refused(self):
        assert interpret_vtpass("Invalid Credentials.", 200).status == "pending"


class TestInterpretVtpass:
    def test_code_000_with_a_delivered_transaction_is_delivered(self):
        outcome = interpret_vtpass(processed("delivered"))
        assert (outcome.status, outcome.code) == ("delivered", "000")

    @pytest.mark.parametrize("status", ["pending", "initiated", "something-new"])
    def test_code_000_with_another_status_is_pending(self, status):
        assert interpret_vtpass(processed(status)).status == "pending"

    @pytest.mark.parametrize("status", ["failed", "reversed"])
    def test_code_000_with_a_failed_status_is_failed(self, status):
        assert interpret_vtpass(processed(status)).status == "failed"

    def test_code_000_without_a_transaction_status_is_pending(self):
        assert interpret_vtpass({"code": "000"}).status == "pending"

    @pytest.mark.parametrize("code", ["016", "091", "013", "017", "018", "019", "030", "040"])
    def test_a_documented_failure_code_is_failed(self, code):
        outcome = interpret_vtpass({"code": code, "response_description": "x"})
        assert (outcome.status, outcome.code) == ("failed", code)

    @pytest.mark.parametrize("code", ["099", "089", "044", "083", "014", "999", "abc"])
    def test_any_other_code_is_pending_so_it_is_requeried(self, code):
        assert interpret_vtpass({"code": code}).status == "pending"

    def test_code_015_marks_a_request_id_vtpass_never_saw(self):
        outcome = interpret_vtpass({"code": "015", "response_description": "INVALID REQUEST ID"})
        assert (outcome.status, outcome.unknown_request) == ("pending", True)

    @pytest.mark.parametrize("payload", [None, "text", 5, [], {}, {"code": 16}])
    def test_an_unreadable_reply_is_pending(self, payload):
        outcome = interpret_vtpass(payload)
        assert (outcome.status, outcome.code) == ("pending", None)

    def test_vtpasss_own_description_is_carried(self):
        assert (
            interpret_vtpass({"code": "018", "response_description": "LOW WALLET BALANCE"}).description
            == "LOW WALLET BALANCE"
        )

    def test_a_missing_confirmation_is_pending(self):
        outcome = no_confirmation("timeout")
        assert (outcome.status, outcome.code) == ("pending", None)
