# SPDX-License-Identifier: AGPL-3.0-or-later
"""A local OpenAI-compatible model for tests: scripted, streaming, and it records what it was sent.

usage: python tests/fake_model.py [port]   (default 9911)
It is not a model: it recognises "pay <amount> to <merchant> for <thing>" and answers around the
tool results it is given, so the host, the connectors and the cards can be exercised with no key. Each tool
call it makes has an id of its own, as a real model's do.
"airtime <amount> to <number> on <network>" asks for an airtime quote.
"status of <quote id>" asks for that quote's status.
"reuse key: <request>" (with an airtime or pay request) sends the same idempotency key every time, as a model
that is not told better does; "twice: <request>" makes the same call twice in one reply.
"echo: <text>" answers with exactly <text> (`\\n` for a newline): a reply of any shape, Markdown included.
"what was the last amount I paid" and "which quote is still open" are answered from the messages it is sent
(scripted_recall.py), so a compacted context is tested by what it still holds.
A request for a summary of an earlier conversation (the host's compaction) is answered by scripted_summary.py;
`POST /v1/_config` with {"summary_mode": "faithful|forgetful|forgets_first|junk|fail", "summary_delay":
seconds per word, "word_delay": seconds per word, "refuse_over_chars": n} changes how it behaves (a request of
more than n characters is refused the way the Bedrock endpoint refuses a prompt that is too long: HTTP 200 and
an error event), and `GET /v1/_reset` puts it back.
Every streamed reply ends with the usage of the request (prompt tokens counted as one per three characters)
when the request asks for it, as the real endpoint does.
The suggestions on the empty home and what follows them are in scripted_intents.py; what it does with the
person's saved notes (remember, save a recipient, forget, recall, send to a saved recipient) is in
scripted_memory.py.
"""

import hashlib
import json
import re
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import scripted_intents
import scripted_memory
import scripted_recall
import scripted_summary

REQUESTS: list[dict] = []
PAY = re.compile(
    r"pay\s+(?P<amount>[₦N]?\s?[\d,.]+\s?k?)\s+to\s+(?P<merchant>.+?)(?:\s+for\s+(?P<what>.+))?$", re.I
)
AIRTIME = re.compile(
    r"airtime\s+(?P<amount>[₦N]?\s?[\d,]+)\s+to\s+(?P<phone>[\d+][\d\s+()-]*)\s+on\s+(?P<network>\w+)$", re.I
)
MENU = re.compile(r"\bmenu\b", re.I)
STATUS = re.compile(r"status of (?P<quote>qt-[0-9a-f]{20})", re.I)
WORD_DELAY = 0.12
DEFAULTS = {
    "summary_mode": "faithful",
    "summary_delay": 0.0,
    "word_delay": WORD_DELAY,
    "refuse_over_chars": 0,
}
CONFIG: dict = dict(DEFAULTS)
STALL_SECONDS = 600
TOO_LONG = (
    "This model's maximum context length is 262144 tokens. Please reduce the length of the input prompt."
)
SLOW = re.compile(r"slow:(?P<words>\d+)(?:@(?P<delay>[\d.]+))?")
ECHO = "echo:"
MODIFIER = re.compile(r"^(?P<how>reuse key|twice):\s*", re.I)
REUSED_KEY = "reused-key-0001"


def last_of(messages: list[dict], role: str) -> dict | None:
    return next((m for m in reversed(messages) if m["role"] == role), None)


def answer(messages: list[dict], tools: list[dict] | None = None) -> dict:
    """Either {"text": ...} or {"tool": name, "arguments": {...}}."""
    if scripted_summary.is_summary_request(messages):
        return summary_answer(messages)
    if recalled := scripted_recall.answer(messages):
        return {"text": recalled}
    if remembered := scripted_memory.answer(messages, tools or []):
        return remembered
    return scripted_intents.answer(messages, tools or []) or _answer(messages, tools or [])


def summary_answer(messages: list[dict]) -> dict:
    mode = CONFIG["summary_mode"]
    if mode == "fail":
        return {"status": 500}
    attempt = 1 if scripted_summary.LEFT_OUT in messages[-1]["content"] else 0
    return {"text": scripted_summary.write(messages, mode, attempt), "delay": CONFIG["summary_delay"]}


def _told(content: str) -> dict | None:
    """The answer to what a card or an event tells the model, or None for anything else."""
    if content.startswith("[card update]"):
        done = "Payment received" in content
        return {
            "text": "Your payment went through. Thank you." if done else "Noted, I will wait for the card."
        }
    if content.startswith("[event]"):
        done = "paid and done" in content
        return {
            "text": "It is done: your payment went through."
            if done
            else "The quote has ended: " + content[8:]
        }
    return None


def _answer(messages: list[dict], tools: list[dict]) -> dict:
    last = messages[-1]
    if last["role"] == "tool":
        text = last["content"]
        if "do not list the items" in text:
            return {"text": "Pick what you like on the card."}
        quoted = text.split(". The approval card")[0]
        return {"text": f"I have prepared this for you: {quoted} Please check the card."}
    content = last["content"] if isinstance(last["content"], str) else ""
    modifier = MODIFIER.match(content) if last["role"] == "user" else None
    how = modifier["how"].lower() if modifier else ""
    content = content[modifier.end() :] if modifier else content
    if last["role"] == "user" and (told := _told(content)):
        return told
    if last["role"] == "user" and content.startswith(ECHO):
        return {"text": content[len(ECHO) :].strip().replace("\\n", "\n")}
    slow = SLOW.match(content) if last["role"] == "user" else None
    if slow:
        words = int(slow["words"])
        return {
            "text": " ".join(f"word{i}" for i in range(words)) + " END",
            "delay": float(slow["delay"] or WORD_DELAY),
        }
    status = STATUS.search(content) if last["role"] == "user" else None
    if status:
        return {"tool": "paystack-pay__get_quote_status", "arguments": {"quote_id": status["quote"]}}
    if last["role"] == "user" and MENU.search(content) and not PAY.search(content.strip()):
        return {"tool": "food-order__search_menu", "arguments": {}}
    airtime = AIRTIME.search(content.strip()) if last["role"] == "user" else None
    if airtime:
        said = airtime["amount"].strip()
        naira = int(re.sub(r"\D", "", said))
        return shaped(
            {
                "tool": "airtime__create_airtime_quote",
                "arguments": {
                    "network": airtime["network"].lower(),
                    "phone": airtime["phone"].strip(),
                    "amount_kobo": naira * 100,
                    "amount_as_user_said": said if said.startswith("₦") else f"₦{naira}",
                },
            },
            how,
        )
    match = PAY.search(content.strip())
    if last["role"] == "user" and match:
        said = match["amount"].strip()
        digits = re.sub(r"[^\d.]", "", said.replace("k", ""))
        kobo = round(float(digits) * (1000 if said.lower().endswith("k") else 1) * 100)
        return shaped(
            {
                "tool": "paystack-pay__create_payment_quote",
                "arguments": {
                    "amount_kobo": kobo,
                    "amount_as_user_said": said if said.startswith("₦") else f"₦{said}",
                    "description": (match["what"] or "payment").strip(),
                    "merchant": match["merchant"].strip(),
                },
            },
            how,
        )
    return {"text": scripted_intents.refusal(tools)}


def shaped(reply: dict, how: str) -> dict:
    if how == "reuse key":
        reply["arguments"]["idempotency_key"] = REUSED_KEY
    if how == "twice":
        reply["repeat"] = 2
    return reply


def wants_usage(request: dict) -> bool:
    return bool((request.get("stream_options") or {}).get("include_usage"))


def usage_of(request: dict) -> dict:
    prompt = (len(json.dumps(request["messages"])) + len(json.dumps(request.get("tools", [])))) // 3
    return {"prompt_tokens": prompt, "completion_tokens": 10, "total_tokens": prompt + 10}


def usage_chunk(usage: dict | None) -> list[bytes]:
    if usage is None:
        return []
    body = {
        "id": "chatcmpl-fake",
        "object": "chat.completion.chunk",
        "model": "fake",
        "choices": [],
        "usage": usage,
    }
    return [f"data: {json.dumps(body)}\n\n".encode()]


def chunk(delta: dict, finish: str | None = None) -> bytes:
    body = {
        "id": "chatcmpl-fake",
        "object": "chat.completion.chunk",
        "model": "fake",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }
    return f"data: {json.dumps(body)}\n\n".encode()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def _send(self, status: int, body: bytes, content_type: str = "application/json") -> None:
        self.send_response(status)
        self.send_header("content-type", content_type)
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/v1/_requests":
            self._send(200, json.dumps(REQUESTS).encode())
        elif self.path == "/v1/_reset":
            REQUESTS.clear()
            CONFIG.update(DEFAULTS)
            self._send(200, b"{}")
        else:
            self._send(404, b"{}")

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("content-length") or 0))
        if self.path == "/v1/_config":
            CONFIG.update(json.loads(body))
            return self._send(200, json.dumps(CONFIG).encode())
        if not self.path.endswith("/chat/completions"):
            return self._send(404, b"{}")
        request = json.loads(body)
        key = self.headers.get("authorization", "")
        key_id = hashlib.sha256(key.encode()).hexdigest()[:8] if key else ""
        REQUESTS.append({"authorization": bool(key), "key_id": key_id, **request})
        if self._misbehaves(request):
            return None
        reply = answer(request["messages"], request.get("tools", []))
        if reply.get("status"):
            return self._send(reply["status"], b'{"error":{"message":"scripted failure"}}')
        if "tool" in reply:
            reply["call_ids"] = [f"call_{time.time_ns()}_{n}" for n in range(reply.get("repeat", 1))]
        if not request.get("stream"):
            message = {"role": "assistant", "content": reply.get("text")}
            if "tool" in reply:
                message["tool_calls"] = [
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {"name": reply["tool"], "arguments": json.dumps(reply["arguments"])},
                    }
                    for call_id in reply["call_ids"]
                ]
            finish = "tool_calls" if "tool" in reply else "stop"
            return self._send(
                200,
                json.dumps(
                    {
                        "choices": [{"index": 0, "message": message, "finish_reason": finish}],
                        "usage": usage_of(request),
                    }
                ).encode(),
            )
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("transfer-encoding", "chunked")
        self.end_headers()
        try:
            for data in self._stream_pieces(reply, usage_of(request) if wants_usage(request) else None):
                self.wfile.write(f"{len(data):x}\r\n".encode() + data + b"\r\n")
                self.wfile.flush()
                time.sleep(reply.get("delay", CONFIG["word_delay"]))
            self.wfile.write(b"0\r\n\r\n")
        except BrokenPipeError, ConnectionResetError:
            pass

    def _misbehaves(self, request: dict) -> bool:
        """Answers the request as an endpoint that is refusing or stalling would; False when it is well."""
        limit = CONFIG["refuse_over_chars"]
        if limit and len(json.dumps(request["messages"]) + json.dumps(request.get("tools", []))) > limit:
            self._send_error_event()
        elif self._stalls(request):
            self._stall(silent=CONFIG["summary_mode"] == "mute" or self._says(request, "mute:"))
        else:
            return False
        return True

    @staticmethod
    def _says(request: dict, start: str) -> bool:
        return str(request["messages"][-1]["content"]).startswith(start)

    @staticmethod
    def _stalls(request: dict) -> bool:
        last = request["messages"][-1]
        summary = scripted_summary.is_summary_request(request["messages"])
        if summary:
            return CONFIG["summary_mode"] in ("hang", "mute")
        return last["role"] == "user" and str(last["content"]).startswith(("hang:", "mute:"))

    def _stall(self, silent: bool = False) -> None:
        if not silent:
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.send_header("transfer-encoding", "chunked")
            self.end_headers()
            self.wfile.flush()
        time.sleep(STALL_SECONDS)

    def _send_error_event(self) -> None:
        body = {"error": {"code": "validation_error", "message": TOO_LONG}}
        self._send(200, f"data: {json.dumps(body)}\n\n".encode(), "text/event-stream")

    @staticmethod
    def _stream_pieces(reply: dict, usage: dict | None = None) -> list[bytes]:
        if "tool" in reply:
            args = json.dumps(reply["arguments"])
            third = len(args) // 3
            parts = [args[:third], args[third : 2 * third], args[2 * third :]]
            pieces = [chunk({"role": "assistant", "content": ""})]
            for index, call_id in enumerate(reply["call_ids"]):
                function = {"name": reply["tool"], "arguments": ""}
                pieces.append(
                    chunk(
                        {
                            "tool_calls": [
                                {"index": index, "id": call_id, "type": "function", "function": function}
                            ]
                        }
                    )
                )
                pieces += [
                    chunk({"tool_calls": [{"index": index, "function": {"arguments": p}}]}) for p in parts
                ]
            return [*pieces, chunk({}, "tool_calls"), *usage_chunk(usage), b"data: [DONE]\n\n"]
        words = re.findall(r"\S+\s*", reply["text"])
        return [
            chunk({"role": "assistant", "content": ""}),
            *[chunk({"content": w}) for w in words],
            chunk({}, "stop"),
            *usage_chunk(usage),
            b"data: [DONE]\n\n",
        ]


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9911
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
