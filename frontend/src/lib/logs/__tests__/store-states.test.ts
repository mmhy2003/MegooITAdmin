import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { WireLine } from "@/lib/logs/socket";
import { wire, type LogSource } from "@/lib/logs/sources";
import { LogStore, RETRY_MS, RETRY_REASONS } from "@/lib/logs/store";

const SERVER = "0b7c6f2e-3d4a-4b5c-8d9e-0f1a2b3c4d5e";
const JOURNAL: LogSource = { kind: "journal", server_id: SERVER, unit: "nginx.service", priority: null, this_boot: false };
const CONTAINER: LogSource = { kind: "container", server_id: SERVER, container_id: "3f2a9c", name: "web" };

const NOW = 1_000_000;

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

function line(seq: number): WireLine {
  return { seq, time: new Date(Date.UTC(2026, 10, 28, 10, 0, seq % 60)).toISOString(), text: `line ${seq}` };
}

/** A store following `sources`, each subscribed under the wire id "w<index>", with a frame queue and a fixed now. */
function following(...sources: LogSource[]) {
  const queue: (() => void)[] = [];
  const onWanted = vi.fn<(sources: LogSource[]) => void>();
  const store = new LogStore({ onWanted, frame: (cb) => queue.push(cb), now: () => NOW });
  const flush = () => {
    for (const cb of queue.splice(0)) cb();
  };
  /** Answers the wanted sources as the socket would, under fresh wire ids. */
  let round = 0;
  const subscribe = () => {
    round += 1;
    store.handle({
      type: "subscribed",
      sources: store.wanted().map((source) => ({ id: `w${sources.indexOf(source)}r${round}`, source: wire(source) })),
      denied: [],
    });
    flush();
  };
  const wireId = (index = 0) => store.snapshot().entries[index].wireId!;
  store.setSources(sources);
  subscribe();
  return { store, onWanted, flush, subscribe, wireId, state: (index = 0) => store.snapshot().entries[index].state };
}

describe("LogStore denied", () => {
  it("marks a denied source as denied and stops wanting it", () => {
    const queue: (() => void)[] = [];
    const store = new LogStore({ onWanted: vi.fn(), frame: (cb) => queue.push(cb), now: () => NOW });
    store.setSources([JOURNAL, CONTAINER]);
    store.handle({
      type: "subscribed",
      sources: [{ id: "w0", source: wire(JOURNAL) }],
      denied: [{ source: wire(CONTAINER), reason: "forbidden" }],
    });
    for (const cb of queue.splice(0)) cb();
    expect(store.snapshot().entries[1].state).toEqual({ state: "denied", reason: "forbidden" });
    expect(store.wanted()).toEqual([JOURNAL]);
  });
});

describe("LogStore retries", () => {
  it("lists the passing reasons", () => {
    expect([...RETRY_REASONS].sort()).toEqual(["ssh_error", "unreachable", "worker_restarted", "worker_unavailable"]);
    expect(RETRY_MS).toEqual([2000, 5000, 15000, 30000, 30000]);
  });

  for (const reason of ["worker_unavailable", "unreachable", "ssh_error"]) {
    it(`retries ${reason} five times after 2, 5, 15, 30 and 30 s`, () => {
      const { store, onWanted, flush, subscribe, wireId, state } = following(JOURNAL);
      for (let attempt = 1; attempt <= 5; attempt += 1) {
        const delay = RETRY_MS[attempt - 1];
        store.handle({ type: "ended", source: wireId(), reason });
        flush();
        expect(state()).toEqual({ state: "retrying", reason, attempt, at: NOW + delay });
        expect(store.snapshot().entries[0].wireId).toBeNull();
        expect(store.wanted()).toEqual([]);
        onWanted.mockClear();
        vi.advanceTimersByTime(delay - 1);
        flush();
        expect(state().state).toBe("retrying");
        vi.advanceTimersByTime(1);
        flush();
        expect(state()).toEqual({ state: "opening" });
        expect(store.wanted()).toEqual([JOURNAL]);
        expect(onWanted).toHaveBeenCalledExactlyOnceWith([JOURNAL]);
        subscribe();
      }
      store.handle({ type: "ended", source: wireId(), reason });
      flush();
      expect(state()).toEqual({ state: "ended", reason, status: null });
      expect(store.wanted()).toEqual([]);
    });
  }

  it("retries a first worker_restarted at once", () => {
    const { store, flush, wireId, state } = following(JOURNAL);
    store.handle({ type: "ended", source: wireId(), reason: "worker_restarted" });
    flush();
    expect(state()).toEqual({ state: "retrying", reason: "worker_restarted", attempt: 1, at: NOW });
    vi.advanceTimersByTime(0);
    flush();
    expect(state()).toEqual({ state: "opening" });
  });

  it("waits RETRY_MS on a later worker_restarted", () => {
    const { store, flush, subscribe, wireId, state } = following(JOURNAL);
    store.handle({ type: "ended", source: wireId(), reason: "unreachable" });
    vi.advanceTimersByTime(RETRY_MS[0]);
    subscribe();
    store.handle({ type: "ended", source: wireId(), reason: "worker_restarted" });
    flush();
    expect(state()).toEqual({ state: "retrying", reason: "worker_restarted", attempt: 2, at: NOW + RETRY_MS[1] });
  });

  it("starts counting again after a backlog", () => {
    const { store, flush, subscribe, wireId, state } = following(JOURNAL);
    store.handle({ type: "ended", source: wireId(), reason: "unreachable" });
    vi.advanceTimersByTime(RETRY_MS[0]);
    subscribe();
    store.handle({ type: "ended", source: wireId(), reason: "unreachable" });
    vi.advanceTimersByTime(RETRY_MS[1]);
    subscribe();
    store.handle({ type: "lines", source: wireId(), lines: [line(1)], backlog: true });
    flush();
    expect(store.snapshot().entries[0].retries).toBe(0);
    store.handle({ type: "ended", source: wireId(), reason: "unreachable" });
    flush();
    expect(state()).toEqual({ state: "retrying", reason: "unreachable", attempt: 1, at: NOW + RETRY_MS[0] });
  });

  it("tries at once on retryNow and drops the timer", () => {
    const { store, onWanted, flush, wireId, state } = following(JOURNAL);
    store.handle({ type: "ended", source: wireId(), reason: "unreachable" });
    onWanted.mockClear();
    store.retryNow(store.snapshot().entries[0].id);
    flush();
    expect(state()).toEqual({ state: "opening" });
    expect(onWanted).toHaveBeenCalledExactlyOnceWith([JOURNAL]);
    vi.advanceTimersByTime(RETRY_MS[0]);
    expect(onWanted).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("drops the timer of a removed source", () => {
    const { store, onWanted, wireId } = following(JOURNAL, CONTAINER);
    store.handle({ type: "ended", source: wireId(), reason: "unreachable" });
    store.setSources([CONTAINER]);
    expect(vi.getTimerCount()).toBe(0);
    onWanted.mockClear();
    vi.advanceTimersByTime(RETRY_MS[0]);
    expect(onWanted).not.toHaveBeenCalled();
  });

  it("clears the timers on dispose", () => {
    const { store, onWanted, wireId } = following(JOURNAL);
    store.handle({ type: "ended", source: wireId(), reason: "unreachable" });
    onWanted.mockClear();
    store.dispose();
    expect(vi.getTimerCount()).toBe(0);
    vi.advanceTimersByTime(RETRY_MS[0]);
    expect(onWanted).not.toHaveBeenCalled();
  });
});

describe("LogStore ended", () => {
  it("ends on an exit, keeping the rows, and reconnects on demand", () => {
    const { store, onWanted, flush, wireId, state } = following(JOURNAL);
    store.handle({ type: "lines", source: wireId(), lines: [line(1), line(2)], backlog: true });
    store.handle({ type: "ended", source: wireId(), reason: "unreachable" });
    vi.advanceTimersByTime(RETRY_MS[0]);
    store.handle({ type: "subscribed", sources: [{ id: "w9", source: wire(JOURNAL) }], denied: [] });
    store.handle({ type: "ended", source: "w9", reason: "exited", status: 1 });
    flush();
    expect(state()).toEqual({ state: "ended", reason: "exited", status: 1 });
    expect(store.snapshot().entries[0].rows).toHaveLength(2);
    expect(store.snapshot().entries[0].retries).toBe(1);
    expect(store.wanted()).toEqual([]);
    expect(vi.getTimerCount()).toBe(0);
    onWanted.mockClear();
    store.reconnect(store.snapshot().entries[0].id);
    flush();
    expect(state()).toEqual({ state: "opening" });
    expect(store.snapshot().entries[0].retries).toBe(0);
    expect(store.snapshot().entries[0].rows).toHaveLength(2);
    expect(onWanted).toHaveBeenCalledExactlyOnceWith([JOURNAL]);
  });

  it("reconnects a denied source", () => {
    const queue: (() => void)[] = [];
    const store = new LogStore({ onWanted: vi.fn(), frame: (cb) => queue.push(cb), now: () => NOW });
    store.setSources([CONTAINER]);
    store.handle({ type: "subscribed", sources: [], denied: [{ source: wire(CONTAINER), reason: "forbidden" }] });
    for (const cb of queue.splice(0)) cb();
    expect(store.wanted()).toEqual([]);
    const id = store.snapshot().entries[0].id;
    store.reconnect(id);
    for (const cb of queue.splice(0)) cb();
    expect(store.snapshot().entries[0].state).toEqual({ state: "opening" });
    expect(store.wanted()).toEqual([CONTAINER]);
  });

  it("ignores an end for an unknown wire id", () => {
    const { store, flush, state } = following(JOURNAL);
    store.handle({ type: "ended", source: "nope", reason: "exited", status: 1 });
    flush();
    expect(state()).toEqual({ state: "opening" });
  });
});

describe("LogStore idle", () => {
  it("is idle when every entry is, and resume reopens them", () => {
    const { store, onWanted, flush, wireId, state } = following(JOURNAL, CONTAINER);
    store.handle({ type: "ended", source: wireId(0), reason: "idle" });
    flush();
    expect(state(0)).toEqual({ state: "idle" });
    expect(store.snapshot().idle).toBe(false);
    store.handle({ type: "ended", source: wireId(1), reason: "idle" });
    flush();
    expect(store.snapshot().idle).toBe(true);
    expect(store.wanted()).toEqual([]);
    onWanted.mockClear();
    store.resume();
    flush();
    expect(state(0)).toEqual({ state: "opening" });
    expect(state(1)).toEqual({ state: "opening" });
    expect(store.snapshot().idle).toBe(false);
    expect(onWanted).toHaveBeenCalledExactlyOnceWith([JOURNAL, CONTAINER]);
  });
});

describe("LogStore socket", () => {
  it("shows the socket's status, a closed one as reconnecting", () => {
    const { store, flush } = following(JOURNAL);
    store.socketStatus("live");
    flush();
    expect(store.snapshot().socket).toBe("live");
    store.socketStatus("reconnecting");
    flush();
    expect(store.snapshot().socket).toBe("reconnecting");
    store.socketStatus("closed");
    flush();
    expect(store.snapshot().socket).toBe("reconnecting");
  });

  it("reopens live entries and forgets every wire id when the socket opens again", () => {
    const { store, flush, wireId, state } = following(JOURNAL, CONTAINER);
    store.handle({ type: "lines", source: wireId(0), lines: [line(1)], backlog: true });
    flush();
    expect(state(0)).toEqual({ state: "live" });
    store.socketOpened();
    flush();
    expect(state(0)).toEqual({ state: "opening" });
    expect(state(1)).toEqual({ state: "opening" });
    expect(store.snapshot().entries.map((e) => e.wireId)).toEqual([null, null]);
    expect(store.snapshot().entries[0].rows).toHaveLength(1);
  });
});
