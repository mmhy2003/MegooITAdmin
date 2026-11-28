import { goTo } from "@/lib/auth/navigate";
import { BACKOFF_MS, NOT_SIGNED_IN_CLOSE } from "@/lib/live-socket";

export type WireLine = { seq: number; time: string; text: string; level?: string; unit?: string; truncated?: boolean };
export type ServerMessage =
  | {
      type: "subscribed";
      sources: { id: string; source: Record<string, unknown> }[];
      denied: { source: Record<string, unknown>; reason: string }[];
    }
  | { type: "lines"; source: string; lines: WireLine[]; backlog?: boolean }
  | { type: "skipped"; source: string; count: number }
  | { type: "ended"; source: string; reason: string; status?: number }
  | { type: "error"; detail: string };
export type LogSocketStatus = "connecting" | "live" | "reconnecting" | "closed";
/** The shortest time between two `active` frames: the worker's idle rule counts in minutes. */
export const ACTIVE_EVERY_MS = 60_000;

export type LogSocketOptions = {
  onMessage: (m: ServerMessage) => void;
  onStatus: (s: LogSocketStatus) => void;
  /** Called after every open, once the remembered sources are sent. */
  onOpen: () => void;
  now?: () => number;
};

/** The address of the log socket on the page's own host. */
export function logsSocketUrl(location: Pick<Location, "protocol" | "host">): string {
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${location.host}/api/ws/logs`;
}

/** The log socket of one viewer: subscribes again after every reconnect and stays open in a hidden tab. */
export class LogSocket {
  readonly #options: LogSocketOptions;
  readonly #now: () => number;
  #socket: WebSocket | null = null;
  #timer: ReturnType<typeof setTimeout> | null = null;
  #attempt = 0;
  #sources: Record<string, unknown>[] = [];
  #lastActive: number | null = null;
  #closed = false;

  constructor(options: LogSocketOptions) {
    this.#options = options;
    this.#now = options.now ?? Date.now;
  }

  /** Remember the sources to follow; connects on the first non-empty set and sends whenever open. */
  subscribe(sources: Record<string, unknown>[]): void {
    if (this.#closed) return;
    this.#sources = sources;
    if (this.#isOpen()) this.#send();
    else if (this.#socket === null && this.#timer === null && sources.length > 0) this.#connect();
  }

  /** Tell the worker someone is watching, at most once per ACTIVE_EVERY_MS and only while open. */
  active(): void {
    if (!this.#isOpen()) return;
    const now = this.#now();
    if (this.#lastActive !== null && now - this.#lastActive < ACTIVE_EVERY_MS) return;
    this.#lastActive = now;
    this.#socket?.send(JSON.stringify({ type: "active" }));
  }

  /** Final: the socket closes and never reconnects. */
  close(): void {
    this.#closed = true;
    this.#clearTimer();
    const socket = this.#socket;
    this.#socket = null;
    socket?.close();
  }

  #isOpen(): boolean {
    return this.#socket?.readyState === WebSocket.OPEN;
  }

  #connect(): void {
    this.#clearTimer();
    const socket = new WebSocket(logsSocketUrl(window.location));
    this.#socket = socket;
    if (this.#attempt === 0) this.#options.onStatus("connecting");
    socket.onopen = () => {
      this.#attempt = 0;
      this.#options.onStatus("live");
      this.#send();
      this.#options.onOpen();
    };
    socket.onmessage = (event: MessageEvent) => {
      let message: ServerMessage;
      try {
        message = JSON.parse(String(event.data)) as ServerMessage;
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
        this.#options.onStatus("closed");
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
    this.#socket?.send(JSON.stringify({ type: "subscribe", sources: this.#sources }));
  }

  #clearTimer(): void {
    if (this.#timer !== null) clearTimeout(this.#timer);
    this.#timer = null;
  }
}
