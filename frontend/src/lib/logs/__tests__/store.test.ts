import { describe, expect, it, vi } from "vitest";
import type { WireLine } from "@/lib/logs/socket";
import { encodeSource, wire, type LogSource } from "@/lib/logs/sources";
import { LogStore, MAX_ROWS, TRIM_BLOCK, type LineRow, type MarkerRow } from "@/lib/logs/store";

const SERVER = "0b7c6f2e-3d4a-4b5c-8d9e-0f1a2b3c4d5e";
const JOURNAL: LogSource = { kind: "journal", server_id: SERVER, unit: "nginx.service", priority: null, this_boot: false };
const FILE: LogSource = { kind: "file", server_id: SERVER, path: "/var/log/syslog" };
const CONTAINER: LogSource = { kind: "container", server_id: SERVER, container_id: "3f2a9c", name: "web" };

function setup() {
  const queue: (() => void)[] = [];
  const onWanted = vi.fn<(sources: LogSource[]) => void>();
  let clock = 5_000;
  const store = new LogStore({ onWanted, frame: (cb) => queue.push(cb), now: () => clock });
  const flush = () => {
    for (const cb of queue.splice(0)) cb();
  };
  return { store, queue, onWanted, flush, setNow: (ms: number) => (clock = ms) };
}

function line(seq: number, text = `line ${seq}`, extra: Partial<WireLine> = {}): WireLine {
  return { seq, time: new Date(Date.UTC(2026, 10, 28, 10, 0, seq % 60)).toISOString(), text, ...extra };
}

/** A store following `sources`, each subscribed under the wire id "w<index>". */
function following(...sources: LogSource[]) {
  const s = setup();
  s.store.setSources(sources);
  s.store.handle({
    type: "subscribed",
    sources: sources.map((source, i) => ({ id: `w${i}`, source: wire(source) })),
    denied: [],
  });
  s.flush();
  return s;
}

function entry(store: LogStore, index = 0) {
  return store.snapshot().entries[index];
}

function lines(store: LogStore, index = 0): LineRow[] {
  return entry(store, index).rows.filter((row): row is LineRow => row.kind === "line");
}

describe("LogStore sources", () => {
  it("keeps the sources in order and reports them as wanted", () => {
    const { store, flush } = setup();
    store.setSources([FILE, JOURNAL]);
    flush();
    expect(store.snapshot().entries.map((e) => e.id)).toEqual([encodeSource(FILE), encodeSource(JOURNAL)]);
    expect(store.snapshot().entries.map((e) => e.state)).toEqual([{ state: "opening" }, { state: "opening" }]);
    expect(store.wanted()).toEqual([FILE, JOURNAL]);
    store.setSources([JOURNAL, CONTAINER, FILE]);
    expect(store.wanted()).toEqual([JOURNAL, CONTAINER, FILE]);
  });

  it("calls onWanted only when the wanted list changes", () => {
    const { store, onWanted } = setup();
    store.setSources([FILE, JOURNAL]);
    expect(onWanted).toHaveBeenCalledTimes(1);
    expect(onWanted).toHaveBeenLastCalledWith([FILE, JOURNAL]);
    store.setSources([{ ...FILE }, { ...JOURNAL }]);
    expect(onWanted).toHaveBeenCalledTimes(1);
    store.setSources([JOURNAL, FILE]);
    expect(onWanted).toHaveBeenCalledTimes(2);
    expect(onWanted).toHaveBeenLastCalledWith([JOURNAL, FILE]);
    store.setSources([JOURNAL]);
    expect(onWanted).toHaveBeenCalledTimes(3);
    expect(onWanted).toHaveBeenLastCalledWith([JOURNAL]);
  });

  it("keeps the rows of a source that stays", () => {
    const { store, flush } = following(FILE, JOURNAL);
    store.handle({ type: "lines", source: "w1", lines: [line(1)], backlog: true });
    store.setSources([JOURNAL, CONTAINER]);
    flush();
    expect(entry(store).id).toBe(encodeSource(JOURNAL));
    expect(entry(store).rows).toHaveLength(1);
    expect(entry(store, 1).state).toEqual({ state: "opening" });
  });
});

describe("LogStore subscribed", () => {
  it("gives each entry its wire id through sameSource", () => {
    const { store, flush } = setup();
    store.setSources([JOURNAL, CONTAINER]);
    store.handle({
      type: "subscribed",
      sources: [
        { id: "c1", source: { server_id: SERVER, kind: "container", container_id: "3f2a9c" } },
        { id: "j1", source: { server_id: SERVER, kind: "journal", unit: "nginx.service", priority: null, this_boot: false } },
      ],
      denied: [],
    });
    flush();
    expect(store.snapshot().entries.map((e) => e.wireId)).toEqual(["j1", "c1"]);
    expect(store.snapshot().entries.map((e) => e.state)).toEqual([{ state: "opening" }, { state: "opening" }]);
  });

  it("marks a denied source as denied and stops wanting it", () => {
    const { store, flush, onWanted } = setup();
    store.setSources([JOURNAL, FILE]);
    store.handle({
      type: "subscribed",
      sources: [{ id: "j1", source: wire(JOURNAL) }],
      denied: [{ source: wire(FILE), reason: "not_allowed" }],
    });
    flush();
    expect(entry(store, 1).state).toEqual({ state: "denied", reason: "not_allowed" });
    expect(entry(store, 1).wireId).toBeNull();
    expect(store.wanted()).toEqual([JOURNAL]);
    expect(onWanted).toHaveBeenLastCalledWith([JOURNAL]);
  });
});

describe("LogStore lines", () => {
  it("adds a backlog as line rows and goes live", () => {
    const { store, flush } = following(JOURNAL);
    store.handle({
      type: "lines",
      source: "w0",
      backlog: true,
      lines: [line(7, "\u001b[31mERROR\u001b[0m disk full"), line(8, "plain", { level: "debug", unit: "nginx.service", truncated: true })],
    });
    flush();
    const id = encodeSource(JOURNAL);
    const [first, second] = lines(store);
    expect(first).toEqual({
      kind: "line",
      key: `${id}:0:7`,
      source: id,
      run: 0,
      seq: 7,
      time: line(7).time,
      ms: Date.parse(line(7).time),
      text: "\u001b[31mERROR\u001b[0m disk full",
      plain: "ERROR disk full",
      level: "error",
      unit: null,
      truncated: false,
    });
    expect(second).toMatchObject({ key: `${id}:0:8`, level: "debug", unit: "nginx.service", truncated: true });
    expect(entry(store).state).toEqual({ state: "live" });
  });

  it("appends live lines", () => {
    const { store, flush } = following(JOURNAL);
    store.handle({ type: "lines", source: "w0", backlog: true, lines: [line(1), line(2)] });
    store.handle({ type: "lines", source: "w0", lines: [line(3)] });
    store.handle({ type: "lines", source: "w0", lines: [line(4), line(5)] });
    flush();
    expect(lines(store).map((row) => row.seq)).toEqual([1, 2, 3, 4, 5]);
  });

  it("adds only the newer lines of a backlog that holds the last row", () => {
    const { store, flush } = following(JOURNAL);
    store.handle({ type: "lines", source: "w0", backlog: true, lines: [line(1), line(2), line(3)] });
    store.handle({ type: "lines", source: "w0", backlog: true, lines: [line(2), line(3), line(4), line(5)] });
    flush();
    expect(entry(store).rows.map((row) => row.kind)).toEqual(["line", "line", "line", "line", "line"]);
    expect(lines(store).map((row) => row.seq)).toEqual([1, 2, 3, 4, 5]);
    expect(entry(store).run).toBe(0);
  });

  it("marks a backlog that does not hold the last row as reconnected, under a new run", () => {
    const { store, flush } = following(JOURNAL);
    store.handle({ type: "lines", source: "w0", backlog: true, lines: [line(1), line(2), line(3)] });
    // Same seq and time as the last row, other text: the worker restarted and numbers from scratch.
    store.handle({ type: "lines", source: "w0", backlog: true, lines: [line(2), line(3, "other")] });
    flush();
    const id = encodeSource(JOURNAL);
    const rows = entry(store).rows;
    expect(rows.map((row) => row.kind)).toEqual(["line", "line", "line", "marker", "line", "line"]);
    const marker = rows[3] as MarkerRow;
    expect(marker).toMatchObject({ marker: "reconnected", source: id, ms: Date.parse(line(3).time) });
    expect(marker.key).toMatch(new RegExp(`^${id.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}:m\\d+$`));
    expect(rows.slice(4).map((row) => row.key)).toEqual([`${id}:1:2`, `${id}:1:3`]);
    expect(entry(store).run).toBe(1);
  });

  it("adds a skipped marker and counts the skipped lines", () => {
    const { store, flush, setNow } = following(JOURNAL);
    setNow(9_000);
    store.handle({ type: "skipped", source: "w0", count: 120 });
    store.handle({ type: "lines", source: "w0", lines: [line(1)] });
    store.handle({ type: "skipped", source: "w0", count: 30 });
    flush();
    const rows = entry(store).rows;
    expect(rows[0]).toMatchObject({ kind: "marker", marker: "skipped", count: 120, ms: 9_000 });
    expect(rows[2]).toMatchObject({ kind: "marker", marker: "skipped", count: 30, ms: Date.parse(line(1).time) });
    expect(rows[0].key).not.toBe(rows[2].key);
    expect(entry(store).skipped).toBe(150);
  });

  it(`keeps at most ${MAX_ROWS} rows, dropping the oldest in blocks of ${TRIM_BLOCK}`, () => {
    const { store, flush } = following(JOURNAL);
    const batch = Array.from({ length: MAX_ROWS }, (_, i) => line(i + 1));
    store.handle({ type: "lines", source: "w0", backlog: true, lines: batch });
    flush();
    expect(entry(store).rows).toHaveLength(10_000);
    expect(entry(store).trimmed).toBe(0);
    store.handle({ type: "lines", source: "w0", lines: [line(10_001)] });
    flush();
    expect(entry(store).rows).toHaveLength(9_001);
    expect(entry(store).trimmed).toBe(1000);
    expect((entry(store).rows[0] as LineRow).seq).toBe(1001);
    expect((entry(store).rows[9_000] as LineRow).seq).toBe(10_001);
  });

  it("ignores messages for an unknown wire id", () => {
    const { store, flush } = following(JOURNAL);
    const before = store.snapshot();
    store.handle({ type: "lines", source: "nope", backlog: true, lines: [line(1)] });
    store.handle({ type: "skipped", source: "nope", count: 4 });
    flush();
    expect(store.snapshot()).toBe(before);
    expect(entry(store).rows).toEqual([]);
    expect(entry(store).skipped).toBe(0);
  });
});

describe("LogStore notify", () => {
  it("runs the listeners once per frame however many messages arrive", () => {
    const { store, queue, flush } = following(JOURNAL, FILE);
    const listener = vi.fn();
    const unsubscribe = store.subscribe(listener);
    for (let seq = 1; seq <= 50; seq++) store.handle({ type: "lines", source: `w${seq % 2}`, lines: [line(seq)] });
    expect(queue).toHaveLength(1);
    expect(listener).not.toHaveBeenCalled();
    flush();
    expect(listener).toHaveBeenCalledTimes(1);
    flush();
    expect(listener).toHaveBeenCalledTimes(1);
    unsubscribe();
    store.handle({ type: "lines", source: "w0", lines: [line(51)] });
    flush();
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it("keeps the snapshot until the next frame, then bumps its version", () => {
    const { store, flush } = following(JOURNAL, FILE);
    const before = store.snapshot();
    store.handle({ type: "lines", source: "w0", lines: [line(1)] });
    expect(store.snapshot()).toBe(before);
    expect(store.snapshot().entries[0].rows).toHaveLength(0);
    flush();
    const after = store.snapshot();
    expect(after).not.toBe(before);
    expect(after.version).toBe(before.version + 1);
    expect(after.entries[0].rows).toHaveLength(1);
    expect(after.entries[0]).not.toBe(before.entries[0]);
    expect(after.entries[1]).toBe(before.entries[1]);
    expect(store.snapshot()).toBe(after);
  });

  it("starts empty, connecting and not idle", () => {
    const { store } = setup();
    expect(store.snapshot()).toEqual({ version: 0, entries: [], socket: "connecting", idle: false });
  });

  it("drops the pending frame on dispose", () => {
    const { store, flush } = following(JOURNAL);
    const listener = vi.fn();
    store.subscribe(listener);
    store.handle({ type: "lines", source: "w0", lines: [line(1)] });
    store.dispose();
    flush();
    expect(listener).not.toHaveBeenCalled();
  });
});
