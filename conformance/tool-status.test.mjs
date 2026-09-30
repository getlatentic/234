// SPDX-License-Identifier: AGPL-3.0-or-later
// What a tool row says, from the rows around it (static/chat/tool-status.js): no stack needed.
import assert from "node:assert/strict";
import test from "node:test";
import { toolStates } from "../host/src/chat/static/chat/tool-status.js";

const ok = { kind: "tool" };
const refused = { kind: "tool", refused: true };
const stopped = { kind: "tool", refused: true, stopped: true };
const words = { kind: "assistant" };
const card = { kind: "card" };
const user = { kind: "user" };
const states = (items, working = false) => toolStates(items, working).filter(Boolean);

test("a call that worked says nothing", () => assert.deepEqual(states([user, ok, words]), ["ok"]));

test("a refusal the model went on from is quiet: a question, a call that worked, or a card", () => {
  assert.deepEqual(states([user, refused, words]), ["refused"]);
  assert.deepEqual(states([user, refused, ok, card, words]), ["refused", "ok"]);
  assert.deepEqual(states([user, refused, card]), ["refused"]);
});

test("two refusals followed by words are both quiet", () => assert.deepEqual(states([user, refused, refused, words]), ["refused", "refused"]));

test("a refusal nothing followed, in a turn that is over, is a failure", () => {
  assert.deepEqual(states([user, refused]), ["failed"]);
  assert.deepEqual(states([user, refused, { kind: "notice" }]), ["failed"]);
  assert.deepEqual(states([user, refused, { kind: "empty" }]), ["failed"]);
});

test("a refusal nothing has followed yet, in a turn still open, is not a failure yet", () => assert.deepEqual(states([user, refused], true), ["refused"]));

test("what the model said in a later turn does not rescue an earlier refusal", () => {
  assert.deepEqual(states([user, refused, user, words]), ["failed"]);
  assert.deepEqual(states([user, refused, { kind: "card_message" }, ok]), ["failed", "ok"]);
  assert.deepEqual(states([user, refused, user], true), ["failed"]);
});

test("a call the person stopped says stopped, whatever follows", () => {
  assert.deepEqual(states([user, stopped]), ["stopped"]);
  assert.deepEqual(states([user, stopped, words]), ["stopped"]);
});

test("rows that are not tool rows get no state", () => assert.deepEqual(toolStates([user, words], false), [null, null]));
