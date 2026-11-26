import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FakeWebSocket, installFakeWebSocket } from "@/__tests__/helpers/fake-websocket";
import { goTo } from "@/lib/auth/navigate";
import { BACKOFF_MS, LiveSocket, type LiveSocketOptions, type LiveStatus, socketUrl } from "@/lib/live-socket";

vi.mock("@/lib/auth/navigate", () => ({ goTo: vi.fn() }));

let visibility: DocumentVisibilityState = "visible";
let statuses: LiveStatus[];
let onMessage: ReturnType<typeof vi.fn<LiveSocketOptions["onMessage"]>>;
let onOpen: ReturnType<typeof vi.fn<LiveSocketOptions["onOpen"]>>;
let live: LiveSocket | null;

function setVisibility(state: DocumentVisibilityState) {
  visibility = state;
  document.dispatchEvent(new Event("visibilitychange"));
}

function start(): LiveSocket {
  live = new LiveSocket({ onMessage, onOpen, onStatus: (s) => statuses.push(s) });
  return live;
}

function latest(): FakeWebSocket {
  return FakeWebSocket.instances[FakeWebSocket.instances.length - 1];
}

function subscribeFrame(serverIds: string[]) {
  return { type: "subscribe", view: "overview", server_ids: serverIds };
}

beforeEach(() => {
  vi.useFakeTimers();
  installFakeWebSocket();
  visibility = "visible";
  Object.defineProperty(document, "visibilityState", { configurable: true, get: () => visibility });
  statuses = [];
  onMessage = vi.fn<LiveSocketOptions["onMessage"]>();
  onOpen = vi.fn<LiveSocketOptions["onOpen"]>();
  live = null;
  window.history.pushState({}, "", "/servers/abc?tab=performance");
});

afterEach(() => {
  live?.close();
  vi.mocked(goTo).mockReset();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("socketUrl", () => {
  it("uses wss under https and ws otherwise", () => {
    expect(socketUrl({ protocol: "https:", host: "a.example" })).toBe("wss://a.example/api/ws/metrics");
    expect(socketUrl({ protocol: "http:", host: "localhost:3000" })).toBe("ws://localhost:3000/api/ws/metrics");
  });
});

describe("LiveSocket", () => {
  it("connects to the page's host and sends a subscription made before the open once it opens", () => {
    start().subscribe("overview", ["b", "a"]);
    expect(FakeWebSocket.instances).toHaveLength(1);
    expect(latest().url).toBe(socketUrl(window.location));
    expect(latest().sent).toEqual([]);
    expect(statuses).toEqual(["connecting"]);

    latest().open();
    expect(latest().sent).toEqual([subscribeFrame(["a", "b"])]);
    expect(onOpen).toHaveBeenCalledTimes(1);
    expect(statuses).toEqual(["connecting", "live"]);
  });

  it("sends a subscription at once while open, and an identical one not again", () => {
    start();
    latest().open();
    live!.subscribe("overview", ["a", "b"]);
    expect(latest().sent).toEqual([subscribeFrame(["a", "b"])]);
    live!.subscribe("overview", ["b", "a"]);
    expect(latest().sent).toHaveLength(1);
    live!.subscribe("full", ["a", "b"]);
    expect(latest().sent).toEqual([subscribeFrame(["a", "b"]), { type: "subscribe", view: "full", server_ids: ["a", "b"] }]);
  });

  it("reconnects after a drop and subscribes again, then asks for a refill", () => {
    start().subscribe("overview", ["a"]);
    latest().open();
    latest().drop(1013);
    expect(statuses.at(-1)).toBe("reconnecting");

    vi.advanceTimersByTime(999);
    expect(FakeWebSocket.instances).toHaveLength(1);
    vi.advanceTimersByTime(1);
    expect(FakeWebSocket.instances).toHaveLength(2);

    latest().open();
    expect(latest().sent).toEqual([subscribeFrame(["a"])]);
    expect(onOpen).toHaveBeenCalledTimes(2);
    expect(statuses.at(-1)).toBe("live");
  });

  it("waits longer after each failed attempt, up to 30 seconds, and starts over after an open", () => {
    start();
    const waits: number[] = [];
    for (let i = 0; i < 7; i++) {
      const count = FakeWebSocket.instances.length;
      latest().drop(1006);
      let waited = 0;
      while (FakeWebSocket.instances.length === count) {
        vi.advanceTimersByTime(1000);
        waited += 1000;
      }
      waits.push(waited);
    }
    expect(waits).toEqual([1000, 2000, 4000, 8000, 16000, 30000, 30000]);
    expect(BACKOFF_MS).toEqual([1000, 2000, 4000, 8000, 16000, 30000]);

    latest().open();
    latest().drop(1006);
    const count = FakeWebSocket.instances.length;
    vi.advanceTimersByTime(1000);
    expect(FakeWebSocket.instances).toHaveLength(count + 1);
  });

  it("goes to sign-in without reconnecting when the session is gone", () => {
    start();
    latest().open();
    latest().drop(4401);
    vi.advanceTimersByTime(60_000);
    expect(FakeWebSocket.instances).toHaveLength(1);
    expect(statuses.at(-1)).toBe("paused");
    expect(goTo).toHaveBeenCalledWith("/login?next=" + encodeURIComponent("/servers/abc?tab=performance"));
  });

  it("closes while the tab is hidden and opens again when it is visible", () => {
    start().subscribe("overview", ["a"]);
    latest().open();
    setVisibility("hidden");
    expect(latest().closedByClient).toBe(true);
    expect(statuses.at(-1)).toBe("paused");
    vi.advanceTimersByTime(60_000);
    expect(FakeWebSocket.instances).toHaveLength(1);

    setVisibility("visible");
    expect(FakeWebSocket.instances).toHaveLength(2);
    latest().open();
    expect(latest().sent).toEqual([subscribeFrame(["a"])]);
    expect(onOpen).toHaveBeenCalledTimes(2);
  });

  it("cancels a pending reconnect when the tab turns hidden", () => {
    start();
    latest().drop(1006);
    setVisibility("hidden");
    vi.advanceTimersByTime(60_000);
    expect(FakeWebSocket.instances).toHaveLength(1);
    expect(statuses.at(-1)).toBe("paused");
  });

  it("starts paused in a hidden tab", () => {
    visibility = "hidden";
    start();
    expect(FakeWebSocket.instances).toHaveLength(0);
    expect(statuses).toEqual(["paused"]);
  });

  it("stays closed after close(), and no longer follows the tab's visibility", () => {
    start();
    latest().open();
    live!.close();
    expect(latest().closedByClient).toBe(true);
    vi.advanceTimersByTime(60_000);
    setVisibility("hidden");
    setVisibility("visible");
    expect(FakeWebSocket.instances).toHaveLength(1);
  });

  it("cancels a pending reconnect on close()", () => {
    start();
    latest().drop(1006);
    live!.close();
    vi.advanceTimersByTime(60_000);
    expect(FakeWebSocket.instances).toHaveLength(1);
  });

  it("ignores a message that is not JSON and passes the others on", () => {
    start();
    latest().open();
    latest().receive("not json");
    expect(onMessage).not.toHaveBeenCalled();
    const message = { type: "error", detail: "invalid_message" };
    latest().receive(message);
    expect(onMessage).toHaveBeenCalledWith(message);
  });
});
