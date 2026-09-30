// SPDX-License-Identifier: AGPL-3.0-or-later
// <chat-account> is the sign-in part of the chats drawer: "Continue with Google" while signed out, the account and
// "Sign out" once in. The Firebase SDK (one vendored file) is fetched only when the person presses the button, or
// when a sign-in that went through a redirect comes back. The page sends the ID token to our server, which checks
// it and sets our own session cookie; the SDK keeps nothing (memory persistence) and is signed out at once.
import { postJson } from "./http.js";

const PENDING = "sign-in-pending";
const REOPEN = "reopen-chats";
const QUIET = new Set(["auth/popup-closed-by-user", "auth/cancelled-popup-request", "auth/user-cancelled"]);
const SAID = {
  redirect: "Opening Google in this tab.",
  failed: "Sign-in did not work. Try again.",
  unavailable: "Sign-in is not available right now.",
};

const remember = (key, value) => {
  try {
    value === null ? sessionStorage.removeItem(key) : sessionStorage.setItem(key, value);
  } catch {
    // A browser that keeps no session storage still signs in; it only loses the drawer reopening.
  }
};
const recalled = (key) => {
  try {
    return sessionStorage.getItem(key);
  } catch {
    return null;
  }
};

customElements.define(
  "chat-account",
  class ChatAccount extends HTMLElement {
    connectedCallback() {
      this.note = this.querySelector('[data-slot="note"]');
      this.addEventListener("click", (event) => {
        const action = event.target.closest("[data-action]")?.dataset.action;
        if (action === "sign-in") this.#signIn();
        if (action === "sign-out") this.#signOut();
      });
      if (recalled(REOPEN) !== null) {
        remember(REOPEN, null);
        customElements.whenDefined("chat-sheet").then(() => this.closest("chat-sheet")?.open());
      }
      if (recalled(PENDING) !== null) this.#finishRedirect();
    }

    #say(text) {
      this.note.textContent = text;
    }

    #busy(on) {
      this.querySelectorAll("button").forEach((button) => {
        button.disabled = on;
      });
    }

    async #sdk() {
      const sdk = await import(this.dataset.sdk);
      const app = sdk.initializeApp({ apiKey: this.dataset.apiKey, authDomain: this.dataset.authDomain, projectId: this.dataset.projectId });
      const auth = sdk.initializeAuth(app, { persistence: sdk.inMemoryPersistence, popupRedirectResolver: sdk.browserPopupRedirectResolver });
      if (this.dataset.emulator) sdk.connectAuthEmulator(auth, this.dataset.emulator, { disableWarnings: true });
      return { sdk, auth };
    }

    async #signIn() {
      this.#say("");
      this.#busy(true);
      try {
        const { sdk, auth } = await this.#sdk();
        const provider = new sdk.GoogleAuthProvider();
        provider.setCustomParameters({ prompt: "select_account" });
        try {
          await this.#exchange(sdk, auth, (await sdk.signInWithPopup(auth, provider)).user);
        } catch (problem) {
          if (problem?.code !== "auth/popup-blocked") throw problem;
          this.#say(SAID.redirect);
          remember(PENDING, "1");
          await sdk.signInWithRedirect(auth, provider);
        }
      } catch (problem) {
        this.#failed(problem);
      }
    }

    async #finishRedirect() {
      remember(PENDING, null);
      this.#busy(true);
      try {
        const { sdk, auth } = await this.#sdk();
        const result = await sdk.getRedirectResult(auth);
        if (result) await this.#exchange(sdk, auth, result.user);
        else this.#busy(false);
      } catch (problem) {
        this.#failed(problem);
      }
    }

    async #exchange(sdk, auth, user) {
      try {
        await postJson(this.dataset.sessionUrl, { idToken: await user.getIdToken() });
      } finally {
        await sdk.signOut(auth).catch(() => undefined);
      }
      remember(REOPEN, "1");
      location.reload();
    }

    #failed(problem) {
      console.warn("sign-in:", problem?.code ?? problem?.status ?? problem?.message);
      this.#busy(false);
      if (QUIET.has(problem?.code)) return;
      this.#say(problem?.status === 503 ? SAID.unavailable : SAID.failed);
    }

    async #signOut() {
      this.#busy(true);
      try {
        await postJson(this.dataset.signoutUrl);
        remember(REOPEN, "1");
        location.reload();
      } catch {
        this.#busy(false);
        this.#say(SAID.failed);
      }
    }
  },
);
