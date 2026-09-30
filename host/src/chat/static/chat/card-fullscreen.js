// SPDX-License-Identifier: AGPL-3.0-or-later
// Full screen for a card, the host's answer to ui/request-display-mode: the <card-frame> element becomes a
// fixed overlay with a bar and a Close button above the card's own frame (which is never moved, so it does
// not reload), and a spacer keeps its place in the page. The rest of the page is inert and does not scroll,
// Tab stays inside, Escape closes, and closing gives back the focus, the scroll position and the frame's
// inline height.
const OVERLAY = [
  "fixed", "inset-0", "z-50", "flex", "flex-col", "bg-ground", "pt-[env(safe-area-inset-top)]",
  "pb-[env(safe-area-inset-bottom)]",
]; // fmt: skip
const FILL = ["h-auto", "min-h-0", "max-w-none", "w-full", "flex-1"];
const INLINE = ["h-64", "-mx-2", "w-[calc(100%+1rem)]", "max-w-100"];
const BAR = "flex min-h-12 shrink-0 items-center justify-between gap-3 border-b border-line px-3";
const CLOSE = "focus-ring min-h-11 cursor-pointer rounded-control px-3 font-medium hover:bg-sunken";

function sentinel(onFocus) {
  const stop = document.createElement("span");
  stop.tabIndex = 0;
  stop.className = "sr-only";
  stop.addEventListener("focus", onFocus);
  return stop;
}

export class FullScreen {
  #saved = null;
  #inert = [];
  #parts = [];
  #spacer = null;

  constructor(host, frame) {
    this.host = host;
    this.frame = frame;
  }

  get active() {
    return this.#saved !== null;
  }

  enter(title) {
    if (this.active) return;
    const { host, frame } = this;
    this.#saved = { focus: document.activeElement, x: scrollX, y: scrollY, height: frame.style.height, overflow: document.documentElement.style.overflow };
    this.#isolate();
    this.#spacer = document.createElement("div");
    this.#spacer.style.height = `${host.getBoundingClientRect().height}px`;
    host.before(this.#spacer);
    document.documentElement.style.overflow = "hidden";
    frame.style.height = "";
    frame.classList.remove(...INLINE);
    frame.classList.add(...FILL);
    host.classList.remove("block");
    host.classList.add(...OVERLAY);
    host.setAttribute("role", "dialog");
    host.setAttribute("aria-modal", "true");
    host.setAttribute("aria-label", title);
    this.#mountBar(title);
    document.addEventListener("keydown", this.#escape);
    this.#close.focus();
  }

  leave() {
    if (!this.active) return;
    const { host, frame } = this;
    const saved = this.#saved;
    this.#saved = null;
    document.removeEventListener("keydown", this.#escape);
    for (const part of this.#parts) part.remove();
    this.#parts = [];
    this.#spacer.remove();
    this.#spacer = null;
    host.classList.remove(...OVERLAY);
    host.classList.add("block");
    for (const name of ["role", "aria-modal", "aria-label"]) host.removeAttribute(name);
    frame.classList.remove(...FILL);
    frame.classList.add(...INLINE);
    frame.style.height = saved.height;
    document.documentElement.style.overflow = saved.overflow;
    for (const node of this.#inert) node.inert = false;
    this.#inert = [];
    scrollTo(saved.x, saved.y);
    if (saved.focus?.isConnected) saved.focus.focus({ preventScroll: true });
  }

  #escape = (event) => {
    if (event.key === "Escape") this.onclose?.();
  };

  #close = null;

  #mountBar(title) {
    const bar = document.createElement("div");
    bar.className = BAR;
    const name = document.createElement("span");
    name.className = "truncate font-semibold";
    name.textContent = title;
    this.#close = document.createElement("button");
    this.#close.type = "button";
    this.#close.className = CLOSE;
    this.#close.textContent = "Close";
    this.#close.setAttribute("aria-label", "Close full screen");
    this.#close.addEventListener("click", () => this.onclose?.());
    bar.append(name, this.#close);
    const first = sentinel(() => this.frame.focus());
    const last = sentinel(() => this.#close.focus());
    this.host.prepend(first, bar);
    this.host.append(last);
    this.#parts = [first, bar, last];
  }

  /** Everything else on the page stops taking focus and stops being read out while the card fills the window. */
  #isolate() {
    for (let node = this.host; node.parentElement; node = node.parentElement) {
      for (const sibling of node.parentElement.children) {
        if (sibling !== node && !sibling.inert) {
          sibling.inert = true;
          this.#inert.push(sibling);
        }
      }
    }
  }
}
