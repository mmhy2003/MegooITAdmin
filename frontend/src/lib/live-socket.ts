import { goTo } from "@/lib/auth/navigate";
import type { LiveMessage } from "@/lib/metrics";

export type LiveView = "overview" | "full";
export type LiveStatus = "connecting" | "live" | "reconnecting" | "paused";
/** The waits before each reconnect; the last one repeats. */
export const BACKOFF_MS = [1000, 2000, 4000, 8000, 16000, 30000];
/** The close code of a socket whose session is missing or ended. */
export const NOT_SIGNED_IN_CLOSE = 4401;

export type LiveSocketOptions = {
  onMessage: (m: LiveMessage) => void;
  onStatus: (s: LiveStatus) => void;
  /** Called after every open: whatever arrived while the socket was down is read again over REST. */
  onOpen: () => void;
};

type Subscription = { view: LiveView; serverIds: string[] };

/** The address of the live metrics socket on the page's own host. */
export function socketUrl(location: Pick<Location, "protocol" | "host">): string {
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${location.host}/api/ws/metrics`;
}

function sameSubscription(a: Subscription | null, b: Subscription): boolean {
  return a !== null && a.view === b.view && a.serverIds.join(",") === b.serverIds.join(",");
}

/** The metrics socket of one page: subscribes again after every reconnect and rests while the tab is hidden. */
export class LiveSocket {
  readonly #options: LiveSocketOptions;
  #socket: WebSocket | null = null;
  #timer: ReturnType<typeof setTimeout> | null = null;
  #attempt = 0;
  #subscription: Subscription | null = null;
  #sent: Subscription | null = null;
  #closed = false;

  constructor(options: LiveSocketOptions) {
    this.#options = options;
    document.addEventListener("visibilitychange", this.#onVisibility);
    if (document.visibilityState === "visible") this.#connect();
    else this.#options.onStatus("paused");
  }

  /** Remember the servers to stream; sent now when open and again after every open. */
  subscribe(view: LiveView, serverIds: string[]): void {
    this.#subscription = { view, serverIds: [...serverIds].sort() };
    if (this.#socket?.readyState === WebSocket.OPEN) this.#send();
  }

  /** Final: the socket closes and never reconnects. */
  close(): void {
    this.#closed = true;
    document.removeEventListener("visibilitychange", this.#onVisibility);
    this.#stop();
  }

  #connect(): void {
    this.#clearTimer();
    const socket = new WebSocket(socketUrl(window.location));
    this.#socket = socket;
    this.#sent = null;
    if (this.#attempt === 0) this.#options.onStatus("connecting");
    socket.onopen = () => {
      this.#attempt = 0;
      this.#options.onStatus("live");
      this.#send();
      this.#options.onOpen();
    };
    socket.onmessage = (event: MessageEvent) => {
      let message: LiveMessage;
      try {
        message = JSON.parse(String(event.data)) as LiveMessage;
      } catch {
        return;
      }
      this.#options.onMessage(message);
    };
    socket.onclose = (event: CloseEvent) => {
      if (this.#socket !== socket) return;
      this.#socket = null;
      if (event.code === NOT_SIGNED_IN_CLOSE) {
        this.close();
        this.#options.onStatus("paused");
        goTo("/login?next=" + encodeURIComponent(window.location.pathname + window.location.search));
        return;
      }
      this.#options.onStatus("reconnecting");
      const wait = BACKOFF_MS[Math.min(this.#attempt, BACKOFF_MS.length - 1)];
      this.#attempt += 1;
      this.#timer = setTimeout(() => this.#connect(), wait);
    };
  }

  #send(): void {
    const subscription = this.#subscription;
    if (subscription === null || sameSubscription(this.#sent, subscription)) return;
    this.#socket?.send(JSON.stringify({ type: "subscribe", view: subscription.view, server_ids: subscription.serverIds }));
    this.#sent = subscription;
  }

  /** Close the socket on purpose and cancel any reconnect. */
  #stop(): void {
    this.#clearTimer();
    const socket = this.#socket;
    this.#socket = null;
    socket?.close();
  }

  #clearTimer(): void {
    if (this.#timer !== null) clearTimeout(this.#timer);
    this.#timer = null;
  }

  readonly #onVisibility = () => {
    if (this.#closed) return;
    if (document.visibilityState === "visible") {
      if (this.#socket === null && this.#timer === null) {
        this.#attempt = 0;
        this.#connect();
      }
      return;
    }
    this.#stop();
    this.#options.onStatus("paused");
  };
}
