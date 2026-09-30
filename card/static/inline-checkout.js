// SPDX-License-Identifier: AGPL-3.0-or-later
// Paystack's checkout as a popup inside the card (Paystack Inline v2, `resumeTransaction(access_code)`), as an
// option: it is used only where it can run, and anywhere it cannot the card opens the checkout link as it always
// did, with nothing for the person to read. The popup is a frame of Paystack's own that fills the window of the
// page that opens it, so the card first asks the host for full screen.
//
// It runs only when the host says it lets a card have Paystack's two origins (`hostCapabilities.sandbox.csp`) and
// offers full screen, the card holds a transaction's access code, the script loads without a policy violation,
// and the popup reports that it has loaded within a time limit. What the popup says about the payment is a hint to
// look again; the server's own record decides.
const InlineCheckout = (() => {
  const SCRIPT = "https://js.paystack.co/v2/inline.js";
  const NEEDS = { resourceDomains: "https://js.paystack.co", frameDomains: "https://checkout.paystack.com" };
  const SCRIPT_MS = 8000;
  const LOAD_MS = 12000;
  let attempt = null;
  let gaveUp = false;

  const approved = (capabilities) =>
    Object.entries(NEEDS).every(([field, origin]) => capabilities.sandbox?.csp?.[field]?.includes(origin));

  /** Whether this host could show the popup: cheap to ask, and free of any request to Paystack. */
  function hostAllows() {
    const { capabilities, context } = McpApp.host();
    return !gaveUp && approved(capabilities) && Boolean(context.availableDisplayModes?.includes("fullscreen"));
  }

  /** The first policy violation the page reports while the popup is being set up, if any. */
  function watchPolicy() {
    const seen = { directive: null };
    const note = (event) => (seen.directive ??= event.violatedDirective);
    addEventListener("securitypolicyviolation", note);
    return {
      stop: () => removeEventListener("securitypolicyviolation", note),
      /** A violation is reported a moment after the request that caused it, so this waits one turn first. */
      async assertClean(what) {
        await new Promise((done) => setTimeout(done, 0));
        if (seen.directive) throw new Error(`${what}: blocked by policy (${seen.directive})`);
      },
    };
  }

  /** A promise that ends when `work` settles or when `ms` pass. */
  function guarded(work, ms, what) {
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error(`${what}: no answer in ${ms} ms`)), ms);
      work(
        (value) => (clearTimeout(timer), resolve(value)),
        (error) => (clearTimeout(timer), reject(error)),
      );
    });
  }

  const loadScript = () =>
    guarded(
      (done, fail) => {
        if (window.PaystackPop) return done();
        const script = document.createElement("script");
        script.src = SCRIPT;
        script.onload = () => done();
        script.onerror = () => fail(new Error("the script did not load"));
        document.head.append(script);
      },
      SCRIPT_MS,
      "script",
    );

  /** Thrown when the person (Close, Escape) or the server ends the attempt while it is still loading. */
  class Stopped extends Error {}
  const unlessStopped = (now) => {
    if (now.stopped) throw new Stopped("the attempt was ended");
  };

  /** Opens the transaction in the popup; resolves once the popup has loaded it. */
  const resume = (now, code, hear) =>
    guarded(
      (done, fail) => {
        now.popup.resumeTransaction(code, {
          onLoad: () => done(),
          onError: (error) => (now.loaded ? hear.error(error) : fail(new Error(error?.message ?? "the popup reported an error"))),
          onSuccess: () => hear.success(),
          onCancel: () => hear.cancel(),
        });
      },
      LOAD_MS,
      "popup",
    );

  const leave = () => McpApp.requestDisplayMode("inline").catch(() => undefined);

  const closeQuietly = (popup) => {
    try {
      popup?.close();
    } catch (error) {
      console.info("Paystack's popup did not close cleanly.", error.message);
    }
  };

  /** Shows the popup full window; throws when it cannot be shown or the attempt is ended on the way. */
  async function show(now, code, hear, policy) {
    await loadScript();
    unlessStopped(now);
    await policy.assertClean("script");
    now.popup = new window.PaystackPop();
    const window_ = await McpApp.requestDisplayMode("fullscreen");
    if (window_?.mode !== "fullscreen") throw new Error("the host would not go full screen");
    unlessStopped(now);
    await resume(now, code, hear);
    await policy.assertClean("popup");
    unlessStopped(now);
    now.loaded = true;
  }

  /**
   * Shows the popup for `code`. Resolves true once it is showing or being loaded, false when it cannot be shown
   * (the card then uses the link, and does not try the popup again). `hear` has `success`, `cancel` and `error`,
   * called after the popup has closed and the card is back in the page. An attempt is held from its first
   * moment, so a second press during the load, or a Close during it, is answered.
   */
  async function open(code, hear) {
    if (attempt) return true;
    if (!code || !hostAllows()) return false;
    const now = { popup: null, loaded: false, stopped: false };
    attempt = now;
    const finish = (say) => () => {
      if (attempt !== now) return;
      attempt = null;
      leave().then(say);
    };
    const policy = watchPolicy();
    try {
      await show(now, code, { success: finish(hear.success), cancel: finish(hear.cancel), error: finish(hear.error) }, policy);
      return true;
    } catch (error) {
      if (attempt === now) attempt = null;
      closeQuietly(now.popup);
      await leave();
      if (error instanceof Stopped) {
        hear.cancel();
        return true;
      }
      gaveUp = true;
      console.info("Paystack's popup could not be used; opening the link instead.", error.message);
      return false;
    } finally {
      policy.stop();
    }
  }

  /** The person left full screen (Close, Escape) while the popup was loading or up: it is dismissed as a cancel. */
  function displayChanged(mode) {
    if (mode !== "inline" || !attempt) return;
    if (attempt.loaded) attempt.popup.cancelTransaction();
    else {
      attempt.stopped = true;
      closeQuietly(attempt.popup);
    }
  }

  /** The server says the quote is over (paid, declined, expired) while the popup is loading or up: put the card back. */
  function dismiss() {
    if (!attempt) return;
    const now = attempt;
    attempt = null;
    now.stopped = true;
    closeQuietly(now.popup);
    void leave();
  }

  return { open, hostAllows, displayChanged, dismiss };
})();
