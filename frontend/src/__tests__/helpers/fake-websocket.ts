import { vi } from "vitest";

/** A WebSocket the test drives by hand: it never connects, and every frame sent is kept as parsed JSON. */
export class FakeWebSocket {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;
  static instances: FakeWebSocket[] = [];

  readonly url: string;
  readyState = FakeWebSocket.CONNECTING;
  sent: unknown[] = [];
  closedByClient = false;
  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  send(data: string): void {
    this.sent.push(JSON.parse(data));
  }

  /** Closing from the browser always reports a normal close (1000). */
  close(): void {
    this.closedByClient = true;
    this.finish(1000);
  }

  /** The server accepts the connection. */
  open(): void {
    this.readyState = FakeWebSocket.OPEN;
    this.onopen?.(new Event("open"));
  }

  /** The server sends `obj` as JSON, or a string as it is. */
  receive(obj: unknown): void {
    const data = typeof obj === "string" ? obj : JSON.stringify(obj);
    this.onmessage?.(new MessageEvent("message", { data }));
  }

  /** The server closes the connection with `code`. */
  drop(code: number): void {
    this.finish(code);
  }

  private finish(code: number): void {
    if (this.readyState === FakeWebSocket.CLOSED) return;
    this.readyState = FakeWebSocket.CLOSED;
    this.onclose?.(new CloseEvent("close", { code }));
  }
}

/** Put FakeWebSocket in place of the global WebSocket, with no instances yet. */
export function installFakeWebSocket(): typeof FakeWebSocket {
  FakeWebSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeWebSocket);
  return FakeWebSocket;
}
