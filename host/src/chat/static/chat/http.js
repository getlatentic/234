// SPDX-License-Identifier: AGPL-3.0-or-later
import { csrfToken } from "./me.js";

export async function postJson(url, body = {}) {
  const token = await csrfToken();
  if (!token) throw Object.assign(new Error("Could not reach the server. Try again."), { status: 0 });
  const response = await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json", "X-CSRFToken": token },
    body: JSON.stringify(body),
    credentials: "same-origin",
  });
  const answer = await response.json().catch(() => ({}));
  if (!response.ok) throw Object.assign(new Error(answer.message ?? answer.error ?? "The request failed."), { status: response.status, answer });
  return answer;
}
