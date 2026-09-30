// SPDX-License-Identifier: AGPL-3.0-or-later
// What a tool row says about its call. A call that worked says nothing. A refused call is a quiet "refused" when
// the model went on in the same turn (a later call that worked, a card, or words to the person, such as the
// question that asks for what was missing), because then the person has nothing to do about the refusal. It is a
// "failed" row, in the failure colour, only when the turn is over and nothing followed it. A call the person
// stopped says "stopped". The turn is what lies between two messages from the person.
const BOUNDARY = new Set(["user", "card_message"]);

const recovers = ({ kind, refused }) => kind === "assistant" || kind === "card" || (kind === "tool" && !refused);

/** `items` are the thread's children as {kind, refused, stopped}; the answer has one state per item (null for a non-tool). */
export function toolStates(items, working) {
  return items.map((item, at) => {
    if (item.kind !== "tool") return null;
    if (!item.refused) return "ok";
    if (item.stopped) return "stopped";
    const end = items.findIndex((later, i) => i > at && BOUNDARY.has(later.kind));
    const rest = items.slice(at + 1, end === -1 ? undefined : end);
    if (rest.some(recovers)) return "refused";
    return working && end === -1 ? "refused" : "failed";
  });
}

/** Reads the thread's rows and writes each tool row's state. */
export function settleTools(thread, working) {
  const children = [...thread.children];
  const items = children.map((el) => ({
    kind: el.dataset.kind === "assistant" && !el.textContent.trim() ? "empty" : el.dataset.kind,
    refused: el.hasAttribute("data-refused"),
    stopped: el.hasAttribute("data-stopped"),
  }));
  toolStates(items, working).forEach((state, i) => state && (children[i].state = state));
}
