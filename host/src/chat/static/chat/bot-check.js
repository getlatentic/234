// SPDX-License-Identifier: AGPL-3.0-or-later
// Cloudflare Turnstile before a visitor's first message (chat/bot_check.py, docs/bot-check.md). Cloudflare's script
// is fetched only now, when there is a first message to send, so the home page itself makes no request beyond
// its own origin. The widget shows itself only if Cloudflare cannot decide without the person, and goes
// again when the token is in hand.
const SCRIPT = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
const BLOCKED = "We could not check that you are a person. Allow challenges.cloudflare.com and try again, or sign in.";
let loading = null;

function load() {
  loading ??= new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = SCRIPT;
    script.async = true;
    script.onload = () => (window.turnstile ? resolve(window.turnstile) : reject(new Error(BLOCKED)));
    script.onerror = () => reject(new Error(BLOCKED));
    document.head.append(script);
  }).catch((problem) => {
    loading = null;
    throw problem;
  });
  return loading;
}

// A token for one first message, from the widget placed in `slot`.
export async function botToken(siteKey, slot) {
  const turnstile = await load();
  let id;
  try {
    return await new Promise((resolve, reject) => {
      id = turnstile.render(slot, {
        sitekey: siteKey,
        action: "start",
        appearance: "interaction-only",
        execution: "execute",
        callback: resolve,
        "error-callback": () => reject(new Error(BLOCKED)),
        "timeout-callback": () => reject(new Error(BLOCKED)),
      });
      turnstile.execute(id);
    });
  } finally {
    if (id !== undefined) turnstile.remove(id);
    slot.replaceChildren();
  }
}
