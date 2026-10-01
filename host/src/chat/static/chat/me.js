// SPDX-License-Identifier: AGPL-3.0-or-later
// What the static home page learns about its visitor from /api/me (views/me.py): the CSRF token, the account,
// the chats. A page the server rendered carries the token in a meta tag and never asks.
let token = document.querySelector('meta[name="csrf-token"]')?.content ?? "";
let source = "";
let loading = null;

export const currentToken = () => token;

// The answer, fetched once; after a failure the next call asks again.
export function loadMe(url = source) {
  source = url;
  loading ??= fetch(url, { credentials: "same-origin", headers: { accept: "application/json" } })
    .then((response) => {
      if (!response.ok) throw new Error(`${url} answered ${response.status}`);
      return response.json();
    })
    .then((me) => {
      token = me.csrf;
      return me;
    })
    .catch((problem) => {
      loading = null;
      throw problem;
    });
  return loading;
}

// The token a request must carry: at once when it is known, otherwise once /api/me has answered.
export async function csrfToken() {
  if (!token && source) await loadMe().catch(() => undefined);
  return token;
}
