// SPDX-License-Identifier: AGPL-3.0-or-later
// Turns an event into the page's markup: a clone of the server's own template for that kind, filled by
// slot. The templates are the same partials Django uses for stored history.
const slotOf = (root, name) => (root.matches?.(`[data-slot="${name}"]`) ? root : root.querySelector(`[data-slot="${name}"]`));

export function fill(root, values) {
  for (const [name, value] of Object.entries(values)) {
    const slot = slotOf(root, name);
    if (slot) slot.textContent = value ?? "";
  }
  return root;
}

export function instance(host, kind) {
  const template = host.querySelector(`template[data-kind="${kind}"]`);
  return document.importNode(template.content.firstElementChild, true);
}

export const builders = {
  user: (host, p) => fill(instance(host, "user"), { text: p.text }),
  card_message: (host, p) => fill(instance(host, "card_message"), { text: p.text }),
  card_context: (host, p) => fill(instance(host, "card_context"), { text: p.text.split("now shows: ").pop().replace(/[. ]+$/, "") }),
  notice: (host, p) => {
    const node = fill(instance(host, "notice"), { text: p.text });
    node.dataset.level = p.level;
    return node;
  },
  tool: (host, p) => {
    const node = instance(host, "tool");
    node.fill(p);
    return node;
  },
  compaction: (host, p) => {
    const node = instance(host, "compaction");
    node.fill(p);
    return node;
  },
  card: (host, p, event) => {
    const node = instance(host, "card");
    Object.assign(node.dataset, { server: p.server, uri: p.resource_uri, ref: event.ref });
    node.results = [p.result];
    return node;
  },
};

export const shownBubble = (host, message) => host.querySelector(`[data-message="${CSS.escape(message)}"]`);

export function assistantBubble(host, message) {
  const found = shownBubble(host, message);
  if (found) return found;
  const node = instance(host, "assistant");
  node.dataset.message = message;
  return node;
}
