// SPDX-License-Identifier: AGPL-3.0-or-later
// The approval card: shows a quote as the server holds it, and lets the person act on it.
// Markup lives in the Django templates (<template> elements); this file only fills them in.
(() => {
  const POLL_MS = 2000;
  const FINISHED = ["succeeded", "attention", "failed", "abandoned", "expired", "declined", "unavailable"];
  const state = { quote: null, token: null, accessCode: null, busy: false, notice: null, shown: "", told: null, polling: false };
  const root = document.getElementById("root");

  const fromTemplate = (id) => document.getElementById(id).content.firstElementChild.cloneNode(true);
  const slot = (node, name) => (node.dataset.slot === name ? node : node.querySelector(`[data-slot="${name}"]`));
  const setText = (node, name, text) => {
    const target = slot(node, name);
    target.textContent = text ?? "";
    target.classList.toggle("hidden", !text);
  };

  // The word and glyph a phase gives itself; a "reason" phase adds the first sentence of the server's message.
  const STATUS = {
    processing: { glyph: "spin", tone: "neutral", text: "Processing" },
    succeeded: { glyph: "ok", tone: "ok" },
    attention: { glyph: "bad", tone: "bad", text: "Refund due", reason: true },
    unavailable: { glyph: "bad", tone: "bad", text: "Not sent", reason: true },
    failed: { glyph: "bad", tone: "bad", text: "Not charged", reason: true },
    abandoned: { glyph: "off", tone: "neutral", text: "Not charged" },
    declined: { glyph: "off", tone: "neutral", text: "Declined" },
    expired: { glyph: "off", tone: "neutral", text: "Expired" },
    gone: { glyph: "off", tone: "neutral", text: "No longer available" },
  };
  const NO_MONEY_MOVED = ["failed", "unavailable", "abandoned", "declined", "expired"];
  const PLAIN_SUB = ["text-sm", "text-ink-3"];
  const PHONE_SUB = ["text-base", "font-medium", "text-ink"];
  const isReference = (label) => /reference|request/i.test(label);
  const firstSentence = (text) => (text ?? "").split(/(?<=[.!?])\s+/)[0];

  // Who the money goes to: the two lines above the amount, and what for below it.
  const whoOf = (q) => {
    const d = q.details;
    switch (d.kind) {
      case "transfer": return d.recipientName;
      case "airtime": return `${d.network} airtime`;
      case "data": return `${d.network} data`;
      default: return q.merchant;
    }
  };
  const subOf = (q) => {
    const d = q.details;
    switch (d.kind) {
      case "transfer": return `${d.bankName} · ${d.accountMasked}`;
      case "airtime":
      case "data": return d.phone;
      case "food": return `${q.phase === "succeeded" ? "Delivered" : "Deliver"} to ${d.area}`;
      default: return q.merchantRef ? `Order ${q.merchantRef}` : "";
    }
  };
  const whatOf = (q) => (q.details.kind === "data" ? q.details.plan : q.details.kind === "airtime" || q.details.kind === "food" ? "" : q.description);

  function rows(pairs) {
    const list = fromTemplate("t-rows");
    for (const [label, value] of pairs) {
      const row = fromTemplate("t-row");
      const cell = slot(row, "value");
      slot(row, "label").textContent = label;
      cell.textContent = value;
      if (isReference(label)) {
        row.classList.remove("justify-between", "gap-4");
        row.classList.add("flex-col", "gap-0.5");
        cell.classList.replace("text-right", "text-left");
        cell.classList.remove("shrink-0", "whitespace-nowrap");
        cell.classList.add("break-all");
        cell.classList.add("font-mono", "text-xs", "text-ink-2");
      }
      slot(list, "rows").append(row);
    }
    return list;
  }

  const basket = (q) => rows([...q.details.lines.map((l) => [`${l.quantity} × ${l.name}`, l.total]), ["Delivery", q.details.deliveryFee]]);

  function tracker(q) {
    const list = fromTemplate("t-tracker");
    q.tracking.steps.forEach((name, index) => {
      const step = fromTemplate("t-step");
      const dot = slot(step, "dot");
      slot(step, "name").textContent = name;
      const restyle = (node, drop, add) => { node.classList.remove(...drop); node.classList.add(...add); };
      if (index < q.tracking.current) {
        restyle(step, ["border-line-strong", "text-ink-3"], ["border-ok", "text-ink-2"]);
        restyle(dot, ["border-line-strong", "bg-raised"], ["border-ok", "bg-ok"]);
        slot(step, "check").classList.remove("hidden");
      }
      if (index === q.tracking.current) {
        restyle(step, ["text-ink-3"], ["font-semibold", "text-ink"]);
        restyle(dot, ["border-line-strong", "bg-raised"], ["border-ink", "bg-ink", "outline-4", "outline-line-strong", "motion-safe:animate-pulse"]);
        step.setAttribute("aria-current", "step");
      }
      slot(list, "steps").append(step);
    });
    return list;
  }

  // What the amount, recipient and plan already say is left out of the receipt.
  const SHOWN_ABOVE = ["Amount", "Mode", "For", "Merchant", "To", "Bank", "Account", "Network", "Number", "Plan", "Total", "Delivered to"];
  const receipt = (q) => rows(q.receipt.lines.filter((l) => !SHOWN_ABOVE.includes(l.label)).map((l) => [l.label, l.value]));

  const otpNote = (hint) => (hint ?? "").split(/(?<=\.)\s+/).filter((sentence) => !/^Enter\b/.test(sentence)).join(" ");

  function actions(q) {
    switch (q.phase) {
      case "awaiting_approval": {
        const node = fromTemplate("t-approval");
        if (q.details.kind === "airtime" || q.details.kind === "data") {
          const tickRow = slot(node, "readback");
          tickRow.classList.replace("hidden", "flex");
          slot(node, "readback-tick").setAttribute("aria-label", `Correct: ${q.details.readBack}`);
        }
        return node;
      }
      case "awaiting_checkout": return fromTemplate("t-checkout");
      case "awaiting_otp": {
        const node = fromTemplate("t-otp");
        setText(node, "hint", otpNote(q.otpHint));
        return node;
      }
      default: return null;
    }
  }

  function showStatus(card, q) {
    const status = STATUS[q.phase];
    if (!status || q.tracking) return;
    const block = slot(card, "status");
    block.classList.remove("hidden");
    block.dataset.tone = status.tone;
    block.querySelector(`[data-glyph="${status.glyph}"]`).classList.remove("hidden");
    setText(card, "status-text", status.text ?? q.receipt?.title ?? "Done");
    if (status.reason) setText(card, "reason", firstSentence(q.message));
  }

  const showNotice = (card, text) => {
    setText(card, "notice", text?.replace(/^[A-Z][A-Z_]+:\s*/, ""));
    const code = card.querySelector('[data-slot="otp"]');
    if (!code || !text) return;
    code.setAttribute("aria-invalid", "true");
    code.setAttribute("aria-describedby", "notice");
  };

  function draw() {
    const q = state.quote;
    document.getElementById("waiting")?.remove();
    const card = fromTemplate("t-card");
    card.dataset.phase = q.phase;
    setText(card, "mode", q.mode.label);
    setText(card, "who", whoOf(q));
    setText(card, "amount", q.amount.display);
    if (NO_MONEY_MOVED.includes(q.phase)) slot(card, "amount").classList.add("line-through", "text-ink-3");
    setText(card, "what", whatOf(q));
    const sub = slot(card, "sub");
    setText(card, "sub", subOf(q));
    if (q.details.kind === "airtime" || q.details.kind === "data") {
      sub.classList.remove(...PLAIN_SUB);
      sub.classList.add(...PHONE_SUB);
    }
    showStatus(card, q);
    const body = slot(card, "body");
    if (q.details.kind === "food" && ["awaiting_approval", "awaiting_checkout"].includes(q.phase)) body.append(basket(q));
    if (q.tracking) body.append(tracker(q));
    if (q.receipt) body.append(receipt(q));
    const controls = actions(q);
    if (controls) slot(card, "actions").append(controls);
    showNotice(card, state.notice);
    root.replaceChildren(card);
    if (state.notice) root.querySelector('[data-slot="otp"]')?.focus();
    syncBusy();
    tick();
  }

  function syncBusy() {
    const readback = root.querySelector('[data-slot="readback-tick"]');
    const needsTick = Boolean(readback) && !readback.closest(".hidden");
    root.querySelectorAll("button").forEach((button) => {
      const blocked = state.busy || (button.dataset.action === "approve" && needsTick && !readback.checked);
      button.disabled = blocked;
    });
  }

  const countdown = (ms) => {
    const total = Math.max(Math.ceil(ms / 1000), 0);
    return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
  };

  function tick() {
    const target = root.querySelector('[data-slot="expiry"]');
    if (!target || state.quote?.phase !== "awaiting_approval") return;
    const left = Date.parse(state.quote.expiresAt) - Date.now();
    target.classList.toggle("hidden", left >= 60000);
    target.textContent = left <= 0 ? "Expired" : `Expires ${countdown(left)}`;
    if (left <= 0 && !state.expiredAsked) {
      state.expiredAsked = true;
      run("verify_quote", {});
    }
  }

  // What a tool result means to this card: a quote, or the reason there is none. A connector that does not know
  // the quote (it was made for another owner: the chat moved to an account) has nothing to act on: the card is over.
  function outcomeOf(result) {
    const refusal = result.isError ? result.content?.find((b) => b.type === "text")?.text ?? "" : "";
    if (/^QUOTE_NOT_FOUND\b/.test(refusal)) return { gone: true, message: refusal };
    if (result.isError) return { message: result.content?.find((b) => b.type === "text")?.text ?? "The request was refused." };
    const quote = result.structuredContent?.quote;
    if (!quote) return { message: result.content?.find((b) => b.type === "text")?.text ?? "The server sent a reply this card cannot show." };
    return { quote, token: result._meta?.approvalToken ?? null, accessCode: result._meta?.paystack?.accessCode ?? null };
  }

  function apply(outcome) {
    if (outcome.gone && state.quote) {
      state.quote = { ...state.quote, phase: "gone", poll: false, checkoutUrl: null, tracking: null, receipt: null };
      state.accessCode = null;
      state.notice = null;
      InlineCheckout.dismiss();
    } else if (outcome.quote) {
      if (outcome.token) state.token = outcome.token;
      if (outcome.accessCode) state.accessCode = outcome.accessCode;
      if (outcome.quote.phase !== "awaiting_checkout") {
        state.accessCode = null;
        InlineCheckout.dismiss();
      }
      if (state.quote?.id !== outcome.quote.id) state.expiredAsked = false;
      state.quote = outcome.quote;
      state.notice = null;
    } else {
      state.notice = outcome.message;
    }
    const shown = JSON.stringify([state.quote, state.notice]);
    if (state.quote && shown !== state.shown) {
      state.shown = shown;
      draw();
    }
    tellModel();
    return outcome;
  }

  function tellModel() {
    const q = state.quote;
    if (!q || !FINISHED.includes(q.phase) || state.told === q.phase) return;
    state.told = q.phase;
    const what = q.receipt?.title ?? q.phase.replace(/_/g, " ");
    const text = `The person's card for quote ${q.id} (${q.amount.display}) now shows: ${what}. ${q.message ?? ""}`.trim();
    McpApp.updateModelContext(text).catch(() => undefined);
  }

  async function call(tool, args) {
    try {
      return outcomeOf(await McpApp.callTool(tool, args));
    } catch {
      return { message: "The connection to the server was lost. This card will try again." };
    }
  }

  async function run(tool, args) {
    state.busy = true;
    syncBusy();
    try {
      return apply(await call(tool, { quote_id: state.quote.id, ...args }));
    } finally {
      state.busy = false;
      syncBusy();
    }
  }

  // The popup is tried first where the host allows it; whatever stops it, the link opens as it always did.
  async function openCheckout() {
    if (!state.accessCode && InlineCheckout.hostAllows()) await run("verify_quote", {});
    if (state.quote.phase !== "awaiting_checkout") return;
    const opened = await InlineCheckout.open(state.accessCode, {
      success: () => run("verify_quote", {}),
      cancel: () => undefined,
      error: () => openLink(),
    });
    if (!opened) await openLink();
  }

  async function openLink() {
    const ok = await McpApp.openLink(state.quote.checkoutUrl).then((r) => r?.isError !== true, () => false);
    if (!ok) apply({ message: 'The checkout window was blocked. Press "Open checkout again".' });
  }

  const actionsByName = {
    approve: async () => {
      const tick = root.querySelector('[data-slot="readback-tick"]');
      const outcome = await run("approve_quote", {
        approval_token: state.token ?? "",
        displayed_amount_kobo: state.quote.amount.kobo,
        readback_confirmed: tick ? tick.checked : false,
      });
      if (outcome.quote?.checkoutUrl) openCheckout();
    },
    decline: () => run("decline_quote", { approval_token: state.token ?? "" }),
    "open-checkout": () => openCheckout(),
    "closed-checkout": () => run("verify_quote", { checkout_closed: true }),
    otp: () => submitOtp(),
  };

  root.addEventListener("click", (event) => {
    const name = event.target.closest("[data-action]")?.dataset.action;
    if (name && actionsByName[name]) actionsByName[name]();
  });
  root.addEventListener("change", syncBusy);
  // A sandboxed view may not submit forms, so the code is sent by the button or by Enter in its field.
  function submitOtp() {
    const code = root.querySelector('[data-slot="otp"]').value.trim();
    if (code.length >= 4) run("submit_otp", { otp: code });
  }
  root.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && event.target.dataset.slot === "otp") submitOtp();
  });

  let lastPoll = 0;
  setInterval(() => {
    tick();
    const q = state.quote;
    if (!q?.poll || state.polling || Date.now() - lastPoll < POLL_MS) return;
    state.polling = true;
    lastPoll = Date.now();
    call("verify_quote", { quote_id: q.id }).then(apply).finally(() => { state.polling = false; });
  }, 1000);

  McpApp.on("ui/notifications/tool-result", (result) => { apply(outcomeOf(result)); });
  McpApp.on("ui/notifications/tool-input", () => undefined);
  McpApp.on("ui/notifications/tool-cancelled", () => apply({ message: "The request was cancelled." }));
  McpApp.on("ui/resource-teardown", () => ({}));
  const themed = (context) => {
    if (context?.theme) for (const theme of ["dark", "light"]) document.documentElement.classList.toggle(theme, context.theme === theme);
  };
  McpApp.on("ui/notifications/host-context-changed", (context) => {
    themed(context);
    if (context?.displayMode) InlineCheckout.displayChanged(context.displayMode);
  });
  themed({ theme: matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light" });

  McpApp.connect({ name: "234 card", version: "0.1.0" }).then(
    (hello) => themed(hello.hostContext),
    (error) => { root.textContent = `Could not connect to the chat: ${error.message}`; },
  );
})();
