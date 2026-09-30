// SPDX-License-Identifier: AGPL-3.0-or-later
// The official a2a-js client against the running host, over the HTTP+JSON binding: the agent card,
// streaming a message, INPUT_REQUIRED for an approval, and subscribing again after a dropped stream.
// a2a-js is a conformance oracle: if it cannot read the server, the server is wrong.
//
// needs the stack. usage: node conformance/a2a-js.mjs
import { ClientFactory, ClientFactoryOptions, RestTransportFactory } from "@a2a-js/sdk/client";
import { Role, TaskState } from "@a2a-js/sdk";
import { HOST, freshLedger, suite } from "./lib.mjs";

const TOKEN = process.env.A2A_TOKEN ?? "dummy-local-a2a-token";
const { check, finish } = suite("A2A: the official JavaScript client");
await freshLedger();

const authed = (token) => (url, init = {}) => fetch(url, { ...init, headers: { ...init.headers, Authorization: `Bearer ${token}` } });

async function connect(token = TOKEN) {
  const options = ClientFactoryOptions.createFrom(ClientFactoryOptions.default, {
    transports: [new RestTransportFactory({ fetchImpl: authed(token) })],
    preferredTransports: ["HTTP+JSON"],
    cardResolver: undefined,
  });
  return new ClientFactory(options).createFromUrl(HOST);
}

const request = (text, taskId = "", contextId = "") => ({
  tenant: "",
  message: {
    messageId: crypto.randomUUID(), contextId, taskId, role: Role.ROLE_USER,
    parts: [{ content: { $case: "text", value: text }, metadata: undefined, filename: "", mediaType: "" }],
    metadata: undefined, extensions: [], referenceTaskIds: [],
  },
  configuration: undefined,
  metadata: undefined,
});

const kindOf = (item) => item.payload?.$case;
const stateOf = (item) => {
  const p = item.payload;
  if (p?.$case === "task") return p.value.status?.state;
  if (p?.$case === "statusUpdate") return p.value.status?.state;
  return undefined;
};
const textOf = (parts) => (parts ?? []).map((p) => (p.content?.$case === "text" ? p.content.value : "")).join("");

function joined(items) {
  const parts = new Map();
  for (const item of items) {
    if (kindOf(item) === "task") for (const a of item.payload.value.artifacts ?? []) parts.set(a.artifactId, textOf(a.parts));
    if (kindOf(item) === "artifactUpdate") {
      const u = item.payload.value;
      parts.set(u.artifact.artifactId, (u.append ? parts.get(u.artifact.artifactId) ?? "" : "") + textOf(u.artifact.parts));
    }
  }
  return [...parts.values()].join("");
}

async function collect(stream) {
  const items = [];
  for await (const item of stream) items.push(item);
  return items;
}

const client = await connect();
check(Boolean(client), "the client reads the agent card and picks the HTTP+JSON binding");

const plain = await collect(client.sendMessageStream(request("hello")));
check(kindOf(plain[0]) === "task" && stateOf(plain[0]) === TaskState.TASK_STATE_SUBMITTED, "a stream opens with the task, submitted");
check(stateOf(plain.at(-1)) === TaskState.TASK_STATE_COMPLETED, "and ends completed");
check(joined(plain).startsWith("I can't do that"), "the reply joins from artifact chunks");

const pay = await collect(client.sendMessageStream(request("Pay ₦2,500 to Demo Kitchen for lunch")));
const waiting = pay.at(-1).payload.value;
check(waiting.status.state === TaskState.TASK_STATE_INPUT_REQUIRED, "a payment ends INPUT_REQUIRED");
const handoff = waiting.status.message.parts.map((p) => p.content).find((c) => c?.$case === "data")?.value?.handoff;
check(String(handoff).startsWith(`${HOST}/join/`), "with a handoff link for the person");
const wire = JSON.stringify(pay);
check(!/approvalToken|approval_token|structuredContent|_meta|resource_uri|sim\/checkout/.test(wire), "no card, token or checkout link reaches the caller");
const task = await client.getTask({ tenant: "", id: pay[0].payload.value.id, historyLength: 0 });
check(task.status.state === TaskState.TASK_STATE_INPUT_REQUIRED, "tasks/get agrees");

const stream = client.sendMessageStream(request("slow:60@0.1"));
const seen = [];
for await (const item of stream) {
  seen.push(item);
  if (seen.filter((i) => kindOf(i) === "artifactUpdate").length >= 4) break;
}
await stream.return?.();
const taskId = seen[0].payload.value.id;
await new Promise((done) => setTimeout(done, 1500));
const resumed = await collect(client.resubscribeTask({ tenant: "", id: taskId }));
check(stateOf(resumed[0]) === TaskState.TASK_STATE_WORKING, "after a dropped stream, resubscribing gives the working task");
check(stateOf(resumed.at(-1)) === TaskState.TASK_STATE_COMPLETED, "and follows it to the end");
const words = joined(resumed).split(/\s+/);
check(words.join(" ") === [...Array(60).keys()].map((i) => `word${i}`).concat("END").join(" "), "snapshot and chunks join into the whole answer, no gaps or repeats");

let refused;
try { await collect((await connect("not-a-real-token-at-all")).sendMessageStream(request("hello"))); } catch (error) { refused = error; }
check(Boolean(refused) && /401|token|auth/i.test(String(refused?.message ?? refused)), `a wrong bearer token is refused (${String(refused?.message ?? refused).slice(0, 60)})`);
finish();
