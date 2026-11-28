import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FakeWebSocket, installFakeWebSocket } from "@/__tests__/helpers/fake-websocket";
import { goTo } from "@/lib/auth/navigate";
import { BACKOFF_MS } from "@/lib/live-socket";
import { ACTIVE_EVERY_MS, LogSocket, type LogSocketStatus, logsSocketUrl, type ServerMessage } from "@/lib/logs/socket";

vi.mock("@/lib/auth/navigate", () => ({ goTo: vi.fn() }));

const JOURNAL = { kind: "journal", server_id: "s1", unit: null, priority: null, this_boot: false };
const FILE = { kind: "file", server_id: "s1", path: "/var/log/syslog" };

let statuses: LogSocketStatus[];
let onMessage: ReturnType<typeof vi.fn<(m: ServerMessage) => void>>;
let onOpen: ReturnType<typeof vi.fn<() => void>>;
let clock: number;
let socket: LogSocket | null;

function start(): LogSocket {
  socket = new LogSocket({ onMessage, onOpen, onStatus: (s) => statuses.push(s), now: () => clock });
  return socket;
}

function latest(): FakeWebSocket {
  return FakeWebSocket.instances[FakeWebSocket.instances.length - 1];
}

beforeEach(() => {
  vi.useFakeTimers();
  installFakeWebSocket();
  statuses = [];
  onMessage = vi.fn<(m: ServerMessage) => void>();
  onOpen = vi.fn<() => void>();
  clock = 1_000_000;
  socket = null;
  window.history.pushState({}, "", "/logs?src=j~s1");
});

afterEach(() => {
  socket?.close();
  vi.mocked(goTo).mockReset();
  vi.unstubAllGlobals();
  vi.useRealTimers();
  Reflect.deleteProperty(document, "visibilityState");
});

describe("logsSocketUrl", () => {
  it("uses wss under https and ws otherwise", () => {
    expect(logsSocketUrl({ protocol: "https:", host: "a.example" })).toBe("wss://a.example/api/ws/logs");
    expect(logsSocketUrl({ protocol: "http:", host: "localhost:3000" })).toBe("ws://localhost:3000/api/ws/logs");
  });
});

describe("LogSocket", () => {
  it("opens nothing until the first subscribe with sources", () => {
    const s = start();
    expect(FakeWebSocket.instances).toHaveLength(0);
    s.subscribe([]);
    expect(FakeWebSocket.instances).toHaveLength(0);
    s.subscribe([JOURNAL]);
    expect(FakeWebSocket.instances).toHaveLength(1);
    expect(latest().url).toBe(`ws://${window.location.host}/api/ws/logs`);
    expect(statuses).toEqual(["connecting"]);
  });

  it("sends the sources once open, and again on every later subscribe, an empty one included", () => {
    const s = start();
    s.subscribe([JOURNAL]);
    expect(latest().sent).toEqual([]);
    latest().open();
    expect(statuses).toEqual(["connecting", "live"]);
    expect(latest().sent).toEqual([{ type: "subscribe", sources: [JOURNAL] }]);
    expect(onOpen).toHaveBeenCalledTimes(1);
    s.subscribe([JOURNAL, FILE]);
    s.subscribe([]);
    expect(latest().sent).toEqual([
      { type: "subscribe", sources: [JOURNAL] },
      { type: "subscribe", sources: [JOURNAL, FILE] },
      { type: "subscribe", sources: [] },
    ]);
    expect(FakeWebSocket.instances).toHaveLength(1);
  });

  it("reconnects with backoff after a drop and sends the remembered sources before onOpen", () => {
    const s = start();
    s.subscribe([JOURNAL]);
    latest().open();
    s.subscribe([FILE]);
    latest().drop(1006);
    expect(statuses.at(-1)).toBe("reconnecting");
    vi.advanceTimersByTime(BACKOFF_MS[0] - 1);
    expect(FakeWebSocket.instances).toHaveLength(1);
    vi.advanceTimersByTime(1);
    expect(FakeWebSocket.instances).toHaveLength(2);
    latest().drop(1006);
    vi.advanceTimersByTime(BACKOFF_MS[1] - 1);
    expect(FakeWebSocket.instances).toHaveLength(2);
    vi.advanceTimersByTime(1);
    expect(FakeWebSocket.instances).toHaveLength(3);
    const third = latest();
    onOpen.mockImplementation(() => expect(third.sent).toEqual([{ type: "subscribe", sources: [FILE] }]));
    third.open();
    expect(onOpen).toHaveBeenCalledTimes(2);
    expect(statuses.at(-1)).toBe("live");
  });

  it("goes to sign-in on 4401 and never reconnects", () => {
    start().subscribe([JOURNAL]);
    latest().open();
    latest().drop(4401);
    expect(statuses.at(-1)).toBe("closed");
    expect(goTo).toHaveBeenCalledWith("/login?next=" + encodeURIComponent("/logs?src=j~s1"));
    vi.advanceTimersByTime(60_000);
    expect(FakeWebSocket.instances).toHaveLength(1);
  });

  it("sends active at most once per ACTIVE_EVERY_MS, and nothing while not open", () => {
    const s = start();
    s.active();
    s.subscribe([JOURNAL]);
    s.active();
    latest().open();
    expect(latest().sent).toEqual([{ type: "subscribe", sources: [JOURNAL] }]);
    s.active();
    clock += ACTIVE_EVERY_MS - 1;
    s.active();
    expect(latest().sent.filter((m) => (m as { type: string }).type === "active")).toHaveLength(1);
    clock += 1;
    s.active();
    expect(latest().sent.filter((m) => (m as { type: string }).type === "active")).toHaveLength(2);
    expect(latest().sent.at(-1)).toEqual({ type: "active" });
  });

  it("stays open when the tab is hidden", () => {
    start().subscribe([JOURNAL]);
    latest().open();
    Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "hidden" });
    document.dispatchEvent(new Event("visibilitychange"));
    expect(latest().closedByClient).toBe(false);
    expect(latest().readyState).toBe(FakeWebSocket.OPEN);
    expect(statuses.at(-1)).toBe("live");
  });

  it("stops reconnecting after close", () => {
    const s = start();
    s.subscribe([JOURNAL]);
    latest().open();
    latest().drop(1006);
    s.close();
    vi.advanceTimersByTime(60_000);
    expect(FakeWebSocket.instances).toHaveLength(1);
  });

  it("closes the open socket on close and reconnects no more", () => {
    const s = start();
    s.subscribe([JOURNAL]);
    latest().open();
    s.close();
    expect(latest().closedByClient).toBe(true);
    s.subscribe([FILE]);
    vi.advanceTimersByTime(60_000);
    expect(FakeWebSocket.instances).toHaveLength(1);
  });

  it("ignores a message that is not JSON and passes the others on", () => {
    start().subscribe([JOURNAL]);
    latest().open();
    latest().receive("not json");
    expect(onMessage).not.toHaveBeenCalled();
    const message = { type: "skipped", source: "a", count: 3 };
    latest().receive(message);
    expect(onMessage).toHaveBeenCalledWith(message);
  });
});
