// SPDX-License-Identifier: AGPL-3.0-or-later
// The static home page (chat/shell.py) holds a chat id that is the same for everyone and nothing of the visitor's.
// This gives the page an id of its own and fills in what /api/me knows. Typing and the starters work before it
// answers; a send waits for the CSRF token (me.js) and for nothing else.
import { loadMe } from "./me.js";

const PLACEHOLDER = "0".repeat(32);
const NOT_LOADED = "Your chats could not be loaded. You can still ask.";

// Every address on the page that names the chat, and its id, get a new random id. `?transport=ws|sse` picks the
// event transport, as the server rendered home allowed.
export function adoptChat(thread) {
  const transport = new URLSearchParams(location.search).get("transport");
  if (transport === "ws" || transport === "sse") thread.dataset.transport = transport;
  const id = Array.from(crypto.getRandomValues(new Uint8Array(16)), (byte) => byte.toString(16).padStart(2, "0")).join("");
  for (const name of thread.getAttributeNames()) {
    const value = thread.getAttribute(name);
    if (value.includes(PLACEHOLDER)) thread.setAttribute(name, value.replaceAll(PLACEHOLDER, id));
  }
}

// `data-me` says what came of asking: "loaded" or "failed".
export async function hydrate(thread) {
  let me;
  try {
    me = await loadMe(thread.dataset.meUrl);
  } catch (problem) {
    console.warn("me:", problem?.message);
    thread.problem(NOT_LOADED);
    thread.dataset.me = "failed";
    return;
  }
  thread.querySelector("chat-account")?.fill(me);
  const memory = me.memory && thread.querySelector('template[data-kind="memory"]');
  if (memory) thread.append(memory.content);
  if (me.botCheck) thread.dataset.botCheck = me.botCheck;
  thread.sheet.fill(me.chats);
  if (me.chats.length || me.signIn) thread.offerChats();
  if (me.problem) thread.refuse(me.problem);
  thread.dataset.me = "loaded";
}
