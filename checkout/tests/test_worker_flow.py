# SPDX-License-Identifier: AGPL-3.0-or-later
"""Quote, approve, pay, verify through the running Worker and its local D1."""

import pytest

from tests.worker_client import BASE_URL, quote_args, quote_of

pytestmark = pytest.mark.worker


async def approve(worker, view, token, **over):
    args = {
        "quote_id": view["id"],
        "approval_token": token,
        "displayed_amount_kobo": view["amount"]["kobo"],
        **over,
    }
    return await worker.call("approve_quote", **args)


async def test_tools_list_declares_visibility_and_the_card(worker):
    tools = {t["name"]: t for t in (await worker.rpc("tools/list"))["result"]["tools"]}
    assert tools["create_payment_quote"]["_meta"]["ui"] == {
        "resourceUri": "ui://paystack-pay/card.html",
        "visibility": ["model"],
    }
    assert tools["approve_quote"]["_meta"]["ui"]["visibility"] == ["app"]
    assert "_meta" not in tools["get_quote_status"]


async def test_a_payment_from_quote_to_receipt(worker):
    made = await worker.call("create_payment_quote", **quote_args())
    view, token = quote_of(made), made["_meta"]["approvalToken"]
    assert view["phase"] == "awaiting_approval"
    assert token not in made["content"][0]["text"]

    approved = quote_of(await approve(worker, view, token))
    assert approved["phase"] == "awaiting_checkout"
    url = approved["checkoutUrl"]
    assert url.startswith(f"{BASE_URL}/sim/checkout/qt-") and url.endswith("-a1")

    pending = quote_of(await worker.call("verify_quote", quote_id=view["id"]))
    assert pending["phase"] == "awaiting_checkout"

    reference = url.rsplit("/", 1)[1]
    page = await worker.http.post(f"{BASE_URL}/sim/checkout/{reference}/pay")
    assert "Paid" in page.text

    paid = quote_of(await worker.call("verify_quote", quote_id=view["id"]))
    assert paid["phase"] == "succeeded"
    assert paid["receipt"]["title"] == "Payment received"
    assert {"label": "Amount", "value": "₦2,500"} in paid["receipt"]["lines"]

    status = await worker.call("get_quote_status", quote_id=view["id"])
    assert quote_of(status)["checkoutUrl"] is None
    assert "succeeded" in status["content"][0]["text"]


async def test_the_model_cannot_approve_without_the_cards_token(worker):
    view = quote_of(await worker.call("create_payment_quote", **quote_args()))
    refused = await approve(worker, view, "not-the-token")
    assert refused["isError"] and refused["content"][0]["text"].startswith("APPROVAL_DENIED")


async def test_the_card_amount_must_match_the_quote(worker):
    made = await worker.call("create_payment_quote", **quote_args())
    refused = await approve(worker, quote_of(made), made["_meta"]["approvalToken"], displayed_amount_kobo=1)
    assert refused["content"][0]["text"].startswith("AMOUNT_MISMATCH")


async def test_a_declined_card_ends_the_quote(worker):
    made = await worker.call("create_payment_quote", **quote_args())
    declined = await worker.call(
        "decline_quote",
        quote_id=quote_of(made)["id"],
        approval_token=made["_meta"]["approvalToken"],
    )
    assert quote_of(declined)["phase"] == "declined"


async def test_a_wrong_amount_in_words_is_refused(worker):
    refused = await worker.call("create_payment_quote", **quote_args(said="₦25,000"))
    assert refused["isError"] and "AMOUNT_MISMATCH" in refused["content"][0]["text"]
    unclear = await worker.call("create_payment_quote", **quote_args(said="about 2k or 3k"))
    assert "AMOUNT_UNCLEAR" in unclear["content"][0]["text"]


async def test_card_numbers_are_refused_in_and_never_echoed(worker):
    refused = await worker.call(
        "create_payment_quote", **quote_args(description="pay with 4084 0840 8408 4081")
    )
    assert refused["content"][0]["text"].startswith("CARD_DATA_REFUSED")


async def test_the_payment_arriving_after_the_window_is_a_refund_due(worker):
    made = await worker.call("create_payment_quote", **quote_args())
    view, token = quote_of(made), made["_meta"]["approvalToken"]
    approved = quote_of(await approve(worker, view, token))
    reference = approved["checkoutUrl"].rsplit("/", 1)[1]
    closed = quote_of(await worker.call("verify_quote", quote_id=view["id"], checkout_closed=True))
    assert closed["phase"] == "abandoned"
    await worker.http.post(f"{BASE_URL}/sim/checkout/{reference}/pay")
    late = quote_of(await worker.call("verify_quote", quote_id=view["id"]))
    assert late["phase"] == "attention"
