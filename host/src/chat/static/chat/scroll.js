// SPDX-License-Identifier: AGPL-3.0-or-later
// Keeps the newest line in view while a reply streams, until the person scrolls up. Sticking is a state of its
// own, not a guess made from the distance at each event: a card that grows or a table that redraws changes the
// distance without the person having moved. The state turns off when they scroll up, on when they get back to
// the bottom, and `onAway` says whether a "Latest" button is worth showing.
const AT_BOTTOM_PX = 48;
const AWAY_PX = 160;

const distance = () => document.documentElement.scrollHeight - scrollY - innerHeight;

export class Follow {
  #stuck;
  #lastY = 0;
  #away = false;

  /** `following` is whether the page starts at the newest line: an empty home has none, and stays where it is. */
  constructor(watched, onAway, following) {
    this.#stuck = following;
    this.onAway = onAway;
    addEventListener("scroll", () => this.#scrolled(), { passive: true });
    new ResizeObserver(() => this.keep()).observe(watched);
  }

  /** Goes to the newest line at once and follows from here. */
  jump({ smooth = false } = {}) {
    this.#stuck = true;
    const behavior = smooth && !matchMedia("(prefers-reduced-motion: reduce)").matches ? "smooth" : "instant";
    scrollTo({ top: document.documentElement.scrollHeight, behavior });
    this.#report();
  }

  /** Stays at the newest line if the person is following it. */
  keep() {
    if (this.#stuck) scrollTo({ top: document.documentElement.scrollHeight, behavior: "instant" });
    this.#report();
  }

  get following() {
    return this.#stuck;
  }

  #scrolled() {
    if (distance() <= AT_BOTTOM_PX) this.#stuck = true;
    else if (scrollY < this.#lastY) this.#stuck = false;
    this.#lastY = scrollY;
    this.#report();
  }

  #report() {
    const away = !this.#stuck && distance() > AWAY_PX;
    if (away === this.#away) return;
    this.#away = away;
    this.onAway(away);
  }
}
