// SPDX-License-Identifier: AGPL-3.0-or-later
// One chat's event stream, from a cursor: a WebSocket to the chat's Durable Object (server push), with
// server-sent events as the fallback when a socket cannot be opened. Either way the server replays what
// the client has not seen and then follows, and the client never trusts the wire for order: the thread
// drops anything at or below its cursor and restarts the stream at a gap.
import { postJson } from "./http.js";

const BACKOFF_MS = [300, 1000, 2000, 4000, 8000];
const HEARTBEAT_MS = 25000;
const SILENCE_MS = 60000;
const WS_ATTEMPTS_BEFORE_SSE = 2;

export class EventStream {
  #socket = null;
  #source = null;
  #retry = 0;
  #timer = null;
  #heartbeat = null;
  #heard = 0;
  #wsFailures = 0;
  #stopped = true;

  constructor({ ticketUrl, eventsUrl, transport, cursor, onEvent, onReset, onStatus }) {
    Object.assign(this, { ticketUrl, eventsUrl, transport, cursor, onEvent, onReset, onStatus });
  }

  get via() {
    return this.#socket ? "ws" : this.#source ? "sse" : null;
  }

  start() {
    this.#stopped = false;
    this.#watchTheNetwork();
    this.#connect();
  }

  stop() {
    this.#stopped = true;
    this.#close();
    clearTimeout(this.#timer);
  }

  restart() {
    this.#close();
    clearTimeout(this.#timer);
    this.#connect();
  }

  #watchTheNetwork() {
    const nudge = () => {
      if (!this.#stopped && !this.via) this.restart();
    };
    addEventListener("online", nudge);
    document.addEventListener("visibilitychange", () => document.visibilityState === "visible" && nudge());
  }

  #useSse() {
    return this.transport === "sse" || (this.transport !== "ws" && this.#wsFailures >= WS_ATTEMPTS_BEFORE_SSE);
  }

  async #connect() {
    if (this.#stopped) return;
    try {
      if (this.#useSse()) this.#openSource();
      else await this.#openSocket();
    } catch {
      this.#lost();
    }
  }

  async #openSocket() {
    const { path } = await postJson(this.ticketUrl);
    const url = new URL(path, location.href);
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
    const socket = new WebSocket(url);
    this.#socket = socket;
    let opened = false;
    socket.onopen = () => {
      opened = true;
      this.#heard = Date.now();
      this.onStatus("open");
      socket.send(JSON.stringify({ attach: this.cursor() }));
      this.#beat(socket);
    };
    socket.onmessage = (message) => {
      this.#heard = Date.now();
      this.#retry = 0;
      this.#wsFailures = 0;
      this.onStatus("open");
      if (message.data !== "pong") this.#deliver(JSON.parse(message.data));
    };
    socket.onclose = () => {
      if (this.#socket !== socket) return;
      this.#socket = null;
      clearInterval(this.#heartbeat);
      if (!opened) this.#wsFailures += 1;
      this.#lost();
    };
  }

  #openSource() {
    const source = new EventSource(`${this.eventsUrl}?since=${this.cursor()}`);
    this.#source = source;
    source.onopen = () => this.onStatus("open");
    source.onmessage = (message) => {
      this.#retry = 0;
      this.onStatus("open");
      this.#deliver(JSON.parse(message.data));
    };
    source.onerror = () => {
      if (this.#source !== source) return;
      source.close();
      this.#source = null;
      this.#lost();
    };
  }

  #deliver(frame) {
    if (frame.reset) this.onReset();
    else this.onEvent(frame);
  }

  #beat(socket) {
    clearInterval(this.#heartbeat);
    this.#heartbeat = setInterval(() => {
      if (Date.now() - this.#heard > SILENCE_MS) socket.close();
      else if (socket.readyState === WebSocket.OPEN) socket.send("ping");
    }, HEARTBEAT_MS);
  }

  #lost() {
    if (this.#stopped) return;
    this.onStatus("lost");
    const wait = BACKOFF_MS[Math.min(this.#retry++, BACKOFF_MS.length - 1)];
    this.#timer = setTimeout(() => this.#connect(), wait);
  }

  #close() {
    clearInterval(this.#heartbeat);
    const socket = this.#socket;
    const source = this.#source;
    this.#socket = this.#source = null;
    socket?.close();
    source?.close();
  }
}
