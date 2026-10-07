# SPDX-License-Identifier: AGPL-3.0-or-later
"""PACT 1.0, Identity profile: the Brand's card, routing before authentication, the personal-agent JWT,
the error envelope, and conversations that belong to one (agent, sub) and one Brand, each User with an owner
of their own. The turn is stood in for by a backend that writes a finished reply into the log."""

import json
import time

import pytest

from chat.models import Chat
from pact.identity import Caller
from pact.models import Context

from .pact_support import ISSUER, Agent, call, envelope, message, pact_installed

pytestmark = pytest.mark.django_db
BRANDS = json.dumps({
    "234": {"name": "234", "description": "Everything"},
    "food": {"name": "Mama Put", "description": "Food only", "connectors": ["food-order"]},
})  # fmt: skip


@pytest.fixture(scope="module")
def agent():
    return Agent()


@pytest.fixture(autouse=True)
def pact_on(settings, monkeypatch, agent, backend):
    with pact_installed(settings, monkeypatch, agent, backend, BRANDS):
        yield


def test_the_card_names_the_interface_and_the_personal_agent_jwt(client):
    card = client.get("/a2a/food/.well-known/agent-card.json").json()
    assert card["supportedInterfaces"] == [
        {"url": "http://localhost:8790/a2a/food", "protocolBinding": "HTTP+JSON", "protocolVersion": "1.0"}
    ]
    jwt = {"httpAuthSecurityScheme": {"scheme": "Bearer", "bearerFormat": "JWT"}}
    assert card["securitySchemes"] == {"paJwt": jwt, "platformJwt": jwt}
    assert card["securityRequirements"] == [{"schemes": {"paJwt": {"list": []}}}]
    assert [s["id"] for s in card["skills"]] == ["food"]


def test_an_unknown_brand_or_route_is_404_or_405_with_no_body_before_authentication(client, agent):
    for brand, route, method in (
        ("nope", ".well-known/agent-card.json", "GET"),
        ("234", "unknown", "GET"),
        ("nope", "tasks", "GET"),
    ):
        answer = call(client, agent, route, method, token=None, brand=brand)
        assert answer.status_code == 404 and answer.content == b""
    for route, method in (
        ("message:send", "GET"),
        ("tasks", "POST"),
        ("tasks/x/pushNotificationConfigs", "DELETE"),
    ):
        answer = call(client, agent, route, method, token=None)
        assert answer.status_code == 405 and answer.content == b""


@pytest.mark.parametrize(
    "token",
    [
        None,
        "not.a.jwt",
        "bearer-without-dots",
    ],
)
def test_no_or_a_malformed_token_is_401_with_the_realm(client, agent, token):
    answer = call(client, agent, "tasks", "GET", token=token or "")
    assert (
        answer.status_code == 401
        and answer["WWW-Authenticate"] == 'Bearer realm="a2a"'
        and answer.content == b""
    )


def test_every_refusal_of_section_3_2_is_401(client, agent):
    now = time.time()
    other = Agent()
    for token in (
        other.token(),
        agent.token(aud="https://234.example/a2a/234"),
        agent.token(now=now + 35, exp=int(now) + 155),
        agent.token(now=now - 200, exp=int(now) - 100),
        agent.token(now=now, exp=int(now) + 301),
        agent.token(iss=f"{ISSUER}/disabled-pa"),
        agent.token(iss="https://stranger.example"),
        agent.token(alg="HS256"),
        agent.token(sub=None),
        agent.token(kid="unpublished"),
    ):
        assert call(client, agent, "tasks", "GET", token=token).status_code == 401


def test_es256_and_rs256_are_both_accepted(client, agent):
    for alg in ("ES256", "RS256"):
        assert call(client, agent, "tasks", "GET", token=agent.token(alg=alg)).status_code == 200


def test_tasks_lists_nothing_and_checks_page_size(client, agent):
    answer = call(client, agent, "tasks?pageSize=20", "GET")
    assert answer.json() == {"tasks": [], "nextPageToken": "", "pageSize": 20, "totalSize": 0}
    assert answer["Content-Type"] == "application/a2a+json"
    assert call(client, agent, "tasks", "GET").json()["pageSize"] == 50
    envelope(call(client, agent, "tasks?pageSize=0", "GET"), 400, "INVALID_ARGUMENT", "INVALID_PARAMS")


def test_task_stream_extended_card_and_push_routes_answer_with_their_errors(client, agent):
    assert (
        envelope(call(client, agent, "tasks/abc", "GET"), 404, "NOT_FOUND", "TASK_NOT_FOUND")
        == "Task not found: abc"
    )
    assert (
        envelope(call(client, agent, "tasks/abc:cancel"), 404, "NOT_FOUND", "TASK_NOT_FOUND")
        == "Task not found: abc"
    )
    envelope(call(client, agent, "message:stream"), 400, "FAILED_PRECONDITION", "UNSUPPORTED_OPERATION")
    envelope(
        call(client, agent, "extendedAgentCard", "GET"), 400, "FAILED_PRECONDITION", "UNSUPPORTED_OPERATION"
    )
    envelope(
        call(client, agent, "tasks/abc/pushNotificationConfigs", "GET"),
        400,
        "FAILED_PRECONDITION",
        "PUSH_NOTIFICATION_NOT_SUPPORTED",
    )


def test_a_message_gets_the_agents_reply_synchronously_in_a_new_context(client, agent, backend):
    answer = call(client, agent, "message:send", body=message("buy airtime"))
    reply = answer.json()["message"]
    assert answer.status_code == 200 and answer["Content-Type"] == "application/a2a+json"
    assert reply["role"] == "ROLE_AGENT" and reply["parts"] == [{"text": "You said: buy airtime"}]
    assert "taskId" not in reply and Context.objects.get(chat_id=reply["contextId"]).brand == "234"


def test_a_context_continues_for_its_user_and_brand_and_no_one_else(client, agent):
    first = call(client, agent, "message:send", body=message("one", contextId=None) | {}).json()["message"]
    context = first["contextId"]
    again = call(client, agent, "message:send", body=message("two", contextId=context)).json()["message"]
    assert again["contextId"] == context
    for token, brand in ((agent.token(sub="user-2"), "234"), (agent.token(), "food")):
        answer = call(
            client, agent, "message:send", body=message("three", contextId=context), token=token, brand=brand
        )
        assert envelope(answer, 400, "INVALID_ARGUMENT", "INVALID_PARAMS") == "Unknown contextId"


def test_a_repeated_message_id_gets_the_stored_reply_without_running_again(client, agent, backend):
    first = call(client, agent, "message:send", body=message("pay", messageId="m-1")).json()["message"]
    ran = len(backend.submitted)
    retry = call(
        client, agent, "message:send", body=message("pay", messageId="m-1", contextId=first["contextId"])
    ).json()
    assert retry["message"] == first and len(backend.submitted) == ran


def test_a_text_part_may_name_its_media_type_but_only_plain_text_is_read(client, agent):
    def sent(part):
        body = {"message": {"messageId": "m-part", "role": "ROLE_USER", "parts": [part]}}
        return call(client, agent, "message:send", body=body)

    plain = sent({"text": "airtime", "mediaType": "text/plain", "metadata": {}, "filename": "note.txt"})
    assert plain.json()["message"]["parts"] == [{"text": "You said: airtime"}]
    for part in (
        {"text": "<b>airtime</b>", "mediaType": "text/html"},
        {"text": "airtime", "url": "https://x"},
    ):
        envelope(sent(part), 400, "INVALID_ARGUMENT", "CONTENT_TYPE_NOT_SUPPORTED")


def test_bad_messages_get_the_errors_the_spec_names(client, agent):
    assert (
        envelope(
            call(client, agent, "message:send", body=message(taskId="task-1")),
            404,
            "NOT_FOUND",
            "TASK_NOT_FOUND",
        )
        == "Task not found"
    )
    envelope(call(client, agent, "message:send", body="{"), 400, "INVALID_ARGUMENT", "INVALID_PARAMS")
    raw = {"message": {"messageId": "m", "role": "ROLE_USER", "parts": [{"raw": "aGVsbG8="}]}}
    envelope(
        call(client, agent, "message:send", body=raw), 400, "INVALID_ARGUMENT", "CONTENT_TYPE_NOT_SUPPORTED"
    )
    envelope(
        call(client, agent, "message:send", body=message(role="ROLE_AGENT")),
        400,
        "INVALID_ARGUMENT",
        "INVALID_PARAMS",
    )
    envelope(
        call(client, agent, "message:send", body=message("   ")), 400, "INVALID_ARGUMENT", "INVALID_PARAMS"
    )


def test_each_user_of_an_agent_has_an_owner_of_their_own_and_a_brand_limits_the_connectors(client, agent):
    a = call(client, agent, "message:send", body=message("x"), token=agent.token(sub="alice")).json()[
        "message"
    ]
    b = call(
        client, agent, "message:send", body=message("x"), token=agent.token(sub="bob"), brand="food"
    ).json()["message"]
    owners = {Chat.objects.get(pk=a["contextId"]).owner, Chat.objects.get(pk=b["contextId"]).owner}
    assert owners == {Caller(ISSUER, "alice").owner, Caller(ISSUER, "bob").owner} and len(owners) == 2
    assert Chat.objects.get(pk=b["contextId"]).connectors == "food-order"


def test_a_rate_limited_user_is_429_with_retry_after(client, agent, backend):
    backend.allow = False
    answer = call(client, agent, "message:send", body=message())
    assert answer.status_code == 429 and answer["Retry-After"] == "60"
