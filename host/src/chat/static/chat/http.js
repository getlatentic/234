// SPDX-License-Identifier: AGPL-3.0-or-later
const csrf = () => document.querySelector('meta[name="csrf-token"]').content;

export async function postJson(url, body = {}) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json", "X-CSRFToken": csrf() },
    body: JSON.stringify(body),
    credentials: "same-origin",
  });
  const answer = await response.json().catch(() => ({}));
  if (!response.ok) throw Object.assign(new Error(answer.message ?? answer.error ?? "The request failed."), { status: response.status, answer });
  return answer;
}
