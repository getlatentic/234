# SPDX-License-Identifier: AGPL-3.0-or-later
"""The official a2a-sdk client against the running host: the agent card, streaming a message, INPUT_REQUIRED
for an approval, continuing that task, subscribing again after a dropped stream, tasks/get, and what the
server refuses. The SDK is the oracle: if it cannot read the server, the server is wrong.

usage: uv run python oracle.py            (HOST_URL, CHECKOUT_URL, A2A_TOKEN in the environment; defaults are the local stack)
"""

import asyncio
import json
import os
import re
import sys
import uuid

import httpx
from a2a.client import ClientConfig, ClientFactory
from a2a.types import a2a_pb2 as pb
from google.protobuf.json_format import MessageToJson

HOST = os.environ.get("HOST_URL", "http://localhost:8901")
CONNECTORS = os.environ.get("CHECKOUT_URL", "http://localhost:8900")
TOKEN = os.environ.get("A2A_TOKEN", "dummy-local-a2a-token")
failed = 0


def check(ok: bool, what: str) -> None:
    global failed
    print(f"  {'PASS' if ok else 'FAIL'}  {what}")
    failed += 0 if ok else 1


def request(text: str, task_id: str = "", context_id: str = "") -> pb.SendMessageRequest:
    message = pb.Message(message_id=uuid.uuid4().hex, role=pb.ROLE_USER, parts=[pb.Part(text=text)])
    message.task_id, message.context_id = task_id, context_id
    return pb.SendMessageRequest(message=message)


async def client(token: str | None = TOKEN):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    http = httpx.AsyncClient(headers=headers, timeout=60)
    config = ClientConfig(httpx_client=http, streaming=True, supported_protocol_bindings=["HTTP+JSON"])
    return await ClientFactory(config).create_from_url(HOST), http


def kind(item: pb.StreamResponse) -> str:
    return item.WhichOneof("payload")


def text_of_artifacts(items: list[pb.StreamResponse]) -> str:
    """What a client that rebuilds the answer from the stream would show."""
    parts: dict[str, str] = {}
    for item in items:
        if kind(item) == "task":
            for artifact in item.task.artifacts:
                parts[artifact.artifact_id] = "".join(p.text for p in artifact.parts)
        elif kind(item) == "artifact_update":
            update = item.artifact_update
            chunk = "".join(p.text for p in update.artifact.parts)
            base = parts.get(update.artifact.artifact_id, "") if update.append else ""
            parts[update.artifact.artifact_id] = base + chunk
    return "".join(parts.values())


def state_of(item: pb.StreamResponse) -> str | None:
    if kind(item) == "task":
        return pb.TaskState.Name(item.task.status.state)
    if kind(item) == "status_update":
        return pb.TaskState.Name(item.status_update.status.state)
    return None


async def collect(stream, until_state: str | None = None) -> list[pb.StreamResponse]:
    items = []
    async for item in stream:
        items.append(item)
    return items


async def a_plain_turn() -> None:
    print("a message that needs no approval")
    a2a, http = await client()
    items = await collect(a2a.send_message(request("hello")))
    states = [s for s in map(state_of, items) if s]
    check(kind(items[0]) == "task" and states[0] == "TASK_STATE_SUBMITTED", f"the stream opens with the task ({states[0]})")
    check(states[-1] == "TASK_STATE_COMPLETED", "it ends completed")
    check(text_of_artifacts(items).startswith("I can't do that"), "the model's words arrive as artifact chunks the client can join")
    check(len([i for i in items if kind(i) == "artifact_update"]) > 2, "in several chunks, not one block")
    await http.aclose()


async def an_approval() -> tuple[str, str]:
    print("a payment that waits for the person")
    a2a, http = await client()
    items = await collect(a2a.send_message(request("Pay ₦2,500 to Demo Kitchen for lunch")))
    last = items[-1].status_update
    task_id = items[0].task.id
    check(pb.TaskState.Name(last.status.state) == "TASK_STATE_INPUT_REQUIRED", "the stream ends INPUT_REQUIRED and closes")
    handoff = next((p.data.struct_value["handoff"] for p in last.status.message.parts if p.HasField("data")), "")
    check(str(handoff).startswith(HOST + "/join/"), "the status names a handoff link for the person")
    wire = "".join(MessageToJson(i) for i in items)
    check(all(word not in wire for word in ("approvalToken", "approval_token", "structuredContent", "_meta", "resource_uri", "/sim/checkout")),
          "no card, approval token or checkout link reaches the caller")
    task = await a2a.get_task(pb.GetTaskRequest(id=task_id))
    check(pb.TaskState.Name(task.status.state) == "TASK_STATE_INPUT_REQUIRED", "tasks/get reports the same state")
    await http.aclose()
    return task_id, str(handoff)


async def waiting_again(task_id: str) -> None:
    print("the same task, continued while the person has not approved")
    a2a, http = await client()
    task = await a2a.get_task(pb.GetTaskRequest(id=task_id))
    items = await collect(a2a.send_message(request("Did it go through?", task_id, task.context_id)))
    check(items[0].task.id == task_id, "a message with the task id continues that task")
    check(state_of(items[-1]) == "TASK_STATE_INPUT_REQUIRED", "and it is still waiting for the person")
    await http.aclose()


async def the_person_approves(handoff: str) -> None:
    """What a person does with the handoff link: open the chat, approve the card, pay on the checkout page."""
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as person:
        page = await person.get(handoff)
        chat = str(page.url).split("/")[4]
        csrf = re.search(r'csrf-token" content="([^"]+)', page.text).group(1)
        card = None
        async with person.stream("GET", f"{HOST}/c/{chat}/events?since=0") as events:
            async for line in events.aiter_lines():
                if line.startswith("data: ") and json.loads(line[6:])["type"] == "card":
                    card = json.loads(line[6:])["payload"]
                    break
        quote = card["result"]["structuredContent"]["quote"]
        approved = await person.post(
            f"{HOST}/c/{chat}/call",
            headers={"X-CSRFToken": csrf},
            json={"server": card["server"], "name": "approve_quote", "arguments": {
                "quote_id": quote["id"], "approval_token": card["result"]["_meta"]["approvalToken"],
                "displayed_amount_kobo": quote["amount"]["kobo"]}},
        )
        check(approved.status_code == 200, "the person, let in by the handoff link, approves on the card")


async def continuing(task_id: str) -> None:
    print("the same task, continued after the approval")
    a2a, http = await client()
    task = await a2a.get_task(pb.GetTaskRequest(id=task_id))
    items = await collect(a2a.send_message(request("Did it go through?", task_id, task.context_id)))
    check(state_of(items[-1]) == "TASK_STATE_COMPLETED", "the task completes")
    ended = await a2a.get_task(pb.GetTaskRequest(id=task_id))
    check(pb.TaskState.Name(ended.status.state) == "TASK_STATE_COMPLETED", "and tasks/get says so")
    await http.aclose()


async def a_dropped_stream() -> None:
    print("a stream that drops, and a subscription that picks it up")
    a2a, http = await client()
    stream = a2a.send_message(request("slow:60@0.1"))
    seen = []
    async for item in stream:
        seen.append(item)
        if len([i for i in seen if kind(i) == "artifact_update"]) >= 4:
            break
    await stream.aclose()
    task_id = seen[0].task.id
    await asyncio.sleep(1.5)
    resumed = await collect(a2a.subscribe(pb.SubscribeToTaskRequest(id=task_id)))
    check(kind(resumed[0]) == "task" and state_of(resumed[0]) == "TASK_STATE_WORKING", "subscribing gives the task as it stands, still working")
    check(state_of(resumed[-1]) == "TASK_STATE_COMPLETED", "and follows it to the end")
    words = text_of_artifacts(resumed).split()
    check(words == [f"word{i}" for i in range(60)] + ["END"], "the snapshot and the chunks after it join into the whole answer, without gaps or repeats")
    ended = None
    try:
        await collect(a2a.subscribe(pb.SubscribeToTaskRequest(id=task_id)))
    except Exception as error:
        ended = error
    check(type(ended).__name__ == "UnsupportedOperationError", f"subscribing to a task that has ended is refused ({type(ended).__name__})")
    await http.aclose()


async def refusals() -> None:
    print("what the server refuses")
    bad, http = await client("not-a-real-token-at-all")
    refused = None
    try:
        await collect(bad.send_message(request("hello")))
    except Exception as error:
        refused = error
    check(refused is not None and "401" in str(refused), f"a wrong bearer token is refused ({type(refused).__name__})")
    await http.aclose()
    async with httpx.AsyncClient(timeout=30) as raw:
        body = json.dumps({"message": {"messageId": "x", "role": "ROLE_USER", "parts": [{"text": "hi"}]}})
        old = await raw.post(f"{HOST}/a2a/message:stream", content=body, headers={"Authorization": f"Bearer {TOKEN}", "A2A-Version": "0.3", "content-type": "application/json"})
        check(old.status_code == 400 and old.json()["error"]["details"][0]["reason"] == "VERSION_NOT_SUPPORTED", "a caller on A2A 0.3 is told the version is not supported")
        none = await raw.post(f"{HOST}/a2a/message:stream", content=body, headers={"Authorization": f"Bearer {TOKEN}", "content-type": "application/json"})
        check(none.status_code == 400, "a caller that names no version is taken for 0.3 and refused")
        pre = await raw.options(f"{HOST}/a2a/message:stream", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
        check("access-control-allow-origin" not in pre.headers, "a browser from a site off the allowlist gets no CORS grant")


async def fresh_ledger() -> None:
    """The payments below spend from the whole daily limit, not from what the suites before this one left."""
    async with httpx.AsyncClient(timeout=30) as http:
        (await http.post(f"{CONNECTORS}/test/reset")).raise_for_status()


async def main() -> None:
    await fresh_ledger()
    await a_plain_turn()
    task_id, handoff = await an_approval()
    await waiting_again(task_id)
    await the_person_approves(handoff)
    await continuing(task_id)
    await a_dropped_stream()
    await refusals()
    print("\nAll checks passed." if not failed else f"\n{failed} check(s) failed.")
    sys.exit(1 if failed else 0)


asyncio.run(main())
