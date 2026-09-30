# SPDX-License-Identifier: AGPL-3.0-or-later
import importlib
import json

import pytest
from django.test import Client

from chat.models import Chat, Event
from turns import kinds

pytestmark = pytest.mark.django_db

TASK = "ab12cd34ef56ab12"
TOKEN = "dummy-token-for-agent-one"
OTHER = "dummy-token-for-agent-two"
HEADERS = {"HTTP_AUTHORIZATION": f"Bearer {TOKEN}", "HTTP_A2A_VERSION": "1.0"}


@pytest.fixture(autouse=True)
def a2a_settings(settings):
    settings.A2A_TOKENS = f"one:{TOKEN},two:{OTHER}"
    settings.A2A_CORS_ORIGINS = ["https://agent.example"]
    settings.PUBLIC_BASE_URL = "http://testserver"


def message(text="Pay ₦2,500 to Demo Kitchen", **fields):
    return {"message": {"messageId": "m1", "role": "ROLE_USER", "parts": [{"text": text}], **fields}}


def post(path, body, **headers):
    return Client().post(
        f"/a2a/{path}", json.dumps(body), content_type="application/json", **{**HEADERS, **headers}
    )


def frames(response) -> list[dict]:
    body = b"".join(response.streaming_content).decode()
    return [json.loads(line[6:]) for line in body.split("\n") if line.startswith("data: ")]


def seed(chat, rows, task=TASK):
    for seq, (type, payload, ref) in enumerate(rows, 1):
        Event.objects.create(
            chat=chat,
            seq=seq,
            type=type,
            payload=payload,
            task=task if type != kinds.CARD_CONTEXT else "",
            ref=ref or "",
            created_at=1_790_000_000_000 + seq,
        )


ANSWERED = [
    (kinds.USER, {"text": "pay"}, None),
    (kinds.TURN_STARTED, {"task": TASK}, None),
    (kinds.TOOL, {"call_id": "c", "tool": "create_payment_quote", "result_text": "ok"}, None),
    (kinds.TEXT, {"message": "m1", "text": "Che"}, None),
    (kinds.TEXT, {"message": "m1", "text": "ck it"}, None),
    (kinds.ASSISTANT, {"message": "m1", "text": "Check it", "finish_reason": "stop", "upto": 3}, None),
]
CARD = (
    kinds.CARD,
    {
        "server": "s",
        "result": {"_meta": {"approvalToken": "tok-secret"}, "structuredContent": {"quote": {"id": "q"}}},
    },
    "q",
)


def owned_chat(name="one"):
    return Chat.objects.create(owner=f"a:{name}")


def test_the_agent_card_is_public_and_names_the_binding_and_the_auth():
    card = Client().get("/.well-known/agent-card.json").json()
    interface = card["supportedInterfaces"][0]
    assert interface == {
        "url": "http://testserver/a2a",
        "protocolBinding": "HTTP+JSON",
        "protocolVersion": "1.0",
    }
    assert card["capabilities"]["streaming"] is True
    assert card["securitySchemes"]["bearer"]["httpAuthSecurityScheme"]["scheme"] == "Bearer"


def test_a_call_without_a_valid_bearer_token_is_refused_and_a_cookie_does_not_help(backend):
    body = json.dumps(message())
    for auth in ({}, {"HTTP_AUTHORIZATION": "Bearer nope"}, {"HTTP_AUTHORIZATION": "Basic abc"}):
        answer = Client().post(
            "/a2a/message:stream", body, content_type="application/json", HTTP_A2A_VERSION="1.0", **auth
        )
        assert answer.status_code == 401 and answer["WWW-Authenticate"] == "Bearer"
        assert answer.json()["error"]["status"] == "UNAUTHENTICATED"
    visitor = Client()
    visitor.get("/")
    assert (
        visitor.post(
            "/a2a/message:stream", body, content_type="application/json", HTTP_A2A_VERSION="1.0"
        ).status_code
        == 401
    )
    assert backend.submitted == []


@pytest.mark.parametrize("version", [None, "", "0.3", "2.0", "1", "one"])
def test_a_caller_that_does_not_speak_1_0_is_told_so(backend, version):
    extra = {} if version is None else {"HTTP_A2A_VERSION": version}
    answer = Client().post(
        "/a2a/message:stream",
        json.dumps(message()),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {TOKEN}",
        **extra,
    )
    error = answer.json()["error"]
    assert answer.status_code == 400 and error["details"][0]["reason"] == "VERSION_NOT_SUPPORTED"


def test_a_patch_version_is_accepted(backend):
    assert post("message:stream", message(), HTTP_A2A_VERSION="1.0.3").status_code == 200


def test_cors_allows_only_the_listed_origins():
    listed = Client().options("/a2a/message:stream", HTTP_ORIGIN="https://agent.example")
    assert listed.status_code == 204 and listed["Access-Control-Allow-Origin"] == "https://agent.example"
    assert "a2a-version" in listed["Access-Control-Allow-Headers"] and listed["Vary"] == "Origin"
    unlisted = Client().options("/a2a/message:stream", HTTP_ORIGIN="https://evil.example")
    assert unlisted.status_code == 204 and "Access-Control-Allow-Origin" not in unlisted
    answered = post("message:stream", message(), HTTP_ORIGIN="https://agent.example")
    assert answered["Access-Control-Allow-Origin"] == "https://agent.example"
    assert "Access-Control-Allow-Origin" not in post(
        "message:stream", message(), HTTP_ORIGIN="https://evil.example"
    )


def test_the_allowlist_cannot_be_a_wildcard(monkeypatch):
    from config import settings as module

    monkeypatch.setenv("A2A_CORS_ORIGINS", "*")
    monkeypatch.setenv("DJANGO_DEBUG", "1")
    with pytest.raises(Exception, match="cannot be \\*"):
        importlib.reload(module)
    monkeypatch.delenv("A2A_CORS_ORIGINS")
    importlib.reload(module)


def test_a_bad_token_list_stops_the_app_at_startup():
    from a2a.auth import parse_tokens

    for bad in ("nocolon", "a:short", "a:0123456789abcdef,a:0123456789abcdef01"):
        with pytest.raises(Exception, match="A2A_TOKENS"):
            parse_tokens(bad)
    assert parse_tokens("a:0123456789abcdef, b:fedcba9876543210") == {
        "a": "0123456789abcdef",
        "b": "fedcba9876543210",
    }


def test_a_message_makes_a_chat_of_the_callers_own_and_the_first_frame_is_the_task(backend):
    answer = post("message:stream", message())
    assert answer.status_code == 200 and answer["Content-Type"] == "text/event-stream"
    chat = Chat.objects.get()
    assert chat.owner == "a:one" and chat.title == "Pay ₦2,500 to Demo Kitchen"
    assert backend.submitted == [(chat.id, kinds.USER, "Pay ₦2,500 to Demo Kitchen", None)]
    first = json.loads(next(iter(answer.streaming_content)).decode().removeprefix("data: "))
    assert first["task"]["id"] == "t1" and first["task"]["contextId"] == chat.id
    assert first["task"]["status"]["state"] == "TASK_STATE_SUBMITTED"


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"message": "hi"},
        {"message": {"role": "ROLE_AGENT", "parts": [{"text": "x"}]}},
        {"message": {"role": "ROLE_USER", "parts": []}},
        {"message": {"role": "ROLE_USER", "parts": [{"data": {"a": 1}}]}},
        {"message": {"role": "ROLE_USER", "parts": [{"text": "x"}, {"data": {}}]}},
    ],
)
def test_a_message_that_is_not_plain_user_text_is_refused_before_anything_is_stored(backend, body):
    answer = post("message:stream", body)
    assert answer.status_code == 400 and answer.json()["error"]["details"][0]["reason"] == "INVALID_PARAMS"
    assert backend.submitted == [] and not Chat.objects.exists()


def test_an_input_the_object_refuses_is_a_bad_request(backend):
    backend.answer = {"error": "too_long", "message": "A message can be up to 500 characters."}
    answer = post("message:stream", message("x" * 501))
    assert answer.status_code == 400 and "500 characters" in answer.json()["error"]["message"]


def test_a_body_that_is_too_large_or_not_json_is_refused(backend):
    assert post("message:stream", {"message": {"parts": [{"text": "x" * 20000}]}}).status_code == 400
    bad = Client().post("/a2a/message:stream", "{oops", content_type="application/json", **HEADERS)
    assert bad.status_code == 400 and bad.json()["error"]["details"][0]["reason"] == "INVALID_REQUEST"


def test_the_model_never_gets_card_data_from_a_caller_because_the_object_refuses_it(backend):
    backend.answer = {"error": "card_data", "message": "That looks like a card number."}
    answer = post("message:stream", message("4242 4242 4242 4242"))
    assert answer.status_code == 400 and "card number" in answer.json()["error"]["message"]


def test_a_caller_over_the_rate_limit_is_told_to_wait(backend):
    backend.allow = False
    assert post("message:stream", message()).status_code == 429
    assert backend.submitted == []


def test_a_finished_task_streams_its_replies_as_artifacts_and_ends_completed(backend):
    chat = owned_chat()
    seed(chat, [*ANSWERED, (kinds.TURN_FINISHED, {"task": TASK, "reason": "completed"}, None)])
    task = Client().get(f"/a2a/tasks/{TASK}", **HEADERS).json()
    assert task["status"]["state"] == "TASK_STATE_COMPLETED"
    assert task["artifacts"] == [{"artifactId": "m1", "name": "answer", "parts": [{"text": "Check it"}]}]


def test_a_working_task_is_streamed_from_its_snapshot_then_each_change_until_it_finishes(
    backend, monkeypatch
):
    from a2a import tasks
    from chat import pacing

    chat = owned_chat()
    seed(chat, ANSWERED[:4])
    later = [
        (5, kinds.TEXT, {"message": "m1", "text": "ck it"}),
        (6, kinds.ASSISTANT, {"message": "m1", "text": "Check it", "finish_reason": "stop", "upto": 3}),
        (7, kinds.TURN_FINISHED, {"task": TASK, "reason": "completed"}),
    ]
    waits = []

    def wait(seconds):
        waits.append(seconds)
        if later:
            seq, type, payload = later.pop(0)
            Event.objects.create(
                chat=chat,
                seq=seq,
                type=type,
                payload=payload,
                task=TASK,
                created_at=1_790_000_000_000 + seq,
            )

    monkeypatch.setattr(pacing, "wait", wait)
    monkeypatch.setattr(tasks.pacing, "wait", wait)
    items = frames(Client().get(f"/a2a/tasks/{TASK}:subscribe", **HEADERS))
    assert items[0]["task"]["status"]["state"] == "TASK_STATE_WORKING"
    assert items[0]["task"]["artifacts"][0]["parts"] == [{"text": "Che"}]
    update = items[1]["artifactUpdate"]
    assert update["artifact"]["parts"] == [{"text": "ck it"}] and update["append"] is True
    assert items[2]["artifactUpdate"]["lastChunk"] is True
    assert items[-1]["statusUpdate"]["status"]["state"] == "TASK_STATE_COMPLETED"
    assert len(items) == 4 and waits


def test_a_task_waiting_for_the_person_says_so_with_a_handoff_and_no_card_or_token(backend):
    chat = owned_chat()
    seed(
        chat,
        [*ANSWERED, CARD, (kinds.TURN_FINISHED, {"task": TASK, "reason": kinds.INPUT_REQUIRED}, None)],
    )
    task = Client().get(f"/a2a/tasks/{TASK}", **HEADERS).json()
    assert task["status"]["state"] == "TASK_STATE_INPUT_REQUIRED"
    parts = task["status"]["message"]["parts"]
    assert parts[0]["text"].startswith("A payment is waiting")
    handoff = parts[1]["data"]["handoff"]
    assert parts[1]["data"]["waiting"] == "approval" and handoff.startswith("http://testserver/join/")
    assert "tok-secret" not in json.dumps(task) and "approvalToken" not in json.dumps(task)
    streamed = frames(Client().get(f"/a2a/tasks/{TASK}:subscribe", **HEADERS))
    assert len(streamed) == 1 and "tok-secret" not in json.dumps(streamed)


def test_the_handoff_link_lets_a_person_into_the_chat_to_approve(backend):
    chat = owned_chat()
    seed(
        chat,
        [*ANSWERED, CARD, (kinds.TURN_FINISHED, {"task": TASK, "reason": kinds.INPUT_REQUIRED}, None)],
    )
    link = (
        Client()
        .get(f"/a2a/tasks/{TASK}", **HEADERS)
        .json()["status"]["message"]["parts"][1]["data"]["handoff"]
    )
    person = Client()
    assert person.get(f"/c/{chat.id}/").status_code == 404
    assert person.get(link.removeprefix("http://testserver")).status_code == 302
    assert person.get(f"/c/{chat.id}/").status_code == 200


def test_a_message_with_the_task_id_continues_a_task_that_waits_and_not_one_that_ended(backend):
    chat = owned_chat()
    seed(
        chat,
        [*ANSWERED, CARD, (kinds.TURN_FINISHED, {"task": TASK, "reason": kinds.INPUT_REQUIRED}, None)],
    )
    backend.answer = {"seq": 8, "task": TASK}
    answer = post("message:send", message("did it go through?", taskId=TASK, contextId=chat.id))
    assert answer.status_code == 200
    assert backend.submitted[-1] == (chat.id, kinds.USER, "did it go through?", TASK)
    Event.objects.create(
        chat=chat,
        seq=9,
        type=kinds.TURN_FINISHED,
        payload={"task": TASK, "reason": "completed"},
        task=TASK,
        created_at=0,
    )
    ended = post("message:stream", message("again", taskId=TASK))
    assert (
        ended.status_code == 400 and ended.json()["error"]["details"][0]["reason"] == "UNSUPPORTED_OPERATION"
    )


def test_tasks_and_contexts_belong_to_the_agent_that_made_them(backend):
    chat = owned_chat("two")
    seed(chat, [*ANSWERED, (kinds.TURN_FINISHED, {"task": TASK, "reason": "completed"}, None)])
    for path in (f"/a2a/tasks/{TASK}", f"/a2a/tasks/{TASK}:subscribe"):
        answer = Client().get(path, **HEADERS)
        assert (
            answer.status_code == 404 and answer.json()["error"]["details"][0]["reason"] == "TASK_NOT_FOUND"
        )
    assert post("message:stream", message(contextId=chat.id)).status_code == 400
    assert post("message:stream", message(taskId=TASK)).status_code == 404
    mine = Client().get(f"/a2a/tasks/{TASK}", HTTP_AUTHORIZATION=f"Bearer {OTHER}", HTTP_A2A_VERSION="1.0")
    assert mine.status_code == 200
    assert Client().get("/a2a/tasks", **HEADERS).json()["tasks"] == []


def test_history_and_the_task_list(backend):
    chat = owned_chat()
    seed(chat, [*ANSWERED, (kinds.TURN_FINISHED, {"task": TASK, "reason": "completed"}, None)])
    task = Client().get(f"/a2a/tasks/{TASK}", {"historyLength": 5}, **HEADERS).json()
    assert task["history"][0]["role"] == "ROLE_USER" and task["history"][0]["parts"] == [{"text": "pay"}]
    assert "history" not in Client().get(f"/a2a/tasks/{TASK}", **HEADERS).json()
    listed = Client().get("/a2a/tasks", {"contextId": chat.id}, **HEADERS).json()
    assert [t["id"] for t in listed["tasks"]] == [TASK]


def test_a_failed_task_carries_the_reason_and_a_task_cannot_be_cancelled(backend):
    chat = owned_chat()
    seed(
        chat,
        [
            (kinds.USER, {"text": "pay"}, None),
            (kinds.TURN_STARTED, {"task": TASK}, None),
            (kinds.NOTICE, {"level": "error", "text": "The model could not be reached."}, None),
            (kinds.TURN_FINISHED, {"task": TASK, "reason": kinds.FAILED}, None),
        ],
    )
    task = Client().get(f"/a2a/tasks/{TASK}", **HEADERS).json()
    assert task["status"]["state"] == "TASK_STATE_FAILED"
    assert task["status"]["message"]["parts"] == [{"text": "The model could not be reached."}]
    cancel = Client().post(f"/a2a/tasks/{TASK}:cancel", "{}", content_type="application/json", **HEADERS)
    assert (
        cancel.status_code == 400 and cancel.json()["error"]["details"][0]["reason"] == "TASK_NOT_CANCELABLE"
    )


def test_a_call_sets_no_visitor_cookie(backend):
    response = post("message:stream", message())
    assert "visitor" not in response.cookies
