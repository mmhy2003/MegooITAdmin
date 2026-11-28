import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useFiltered } from "@/components/logs/use-filtered";
import { FilterCache, SLICE } from "@/lib/logs/filter";
import type { LevelGroup } from "@/lib/logs/levels";
import { DEFAULT_SETTINGS, type ViewSettings } from "@/lib/logs/sources";
import type { LineRow, Row } from "@/lib/logs/store";

function line(source: string, seq: number, text: string, level: LevelGroup = "none"): LineRow {
  return {
    kind: "line", key: `${source}:0:${seq}`, source, run: 0, seq, time: "", ms: seq, text, plain: text, level,
    unit: null, truncated: false,
  };
}

function lines(source: string, count: number): Row[] {
  return Array.from({ length: count }, (_, i) => line(source, i, i % 2 === 0 ? `even ${i}` : `odd ${i}`));
}

/** The frames asked for and not yet run or cancelled, by ID. */
let frames: Map<number, FrameRequestCallback>;
let nextId: number;
beforeEach(() => {
  frames = new Map();
  nextId = 0;
  vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => {
    nextId += 1;
    frames.set(nextId, cb);
    return nextId;
  });
  vi.stubGlobal("cancelAnimationFrame", (id: number) => frames.delete(id));
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

/** Runs the frames asked for so far; returns how many there were. */
function runFrames(): number {
  const now = [...frames.values()];
  frames.clear();
  act(() => now.forEach((cb) => cb(0)));
  return now.length;
}

function hook(lists: Row[][], settings: ViewSettings) {
  return renderHook(({ lists, settings }) => useFiltered(lists, settings), { initialProps: { lists, settings } });
}

describe("useFiltered", () => {
  it("returns every row and no filter by default", () => {
    const a = [line("a", 0, "one"), line("a", 1, "two")];
    const { result } = hook([a], DEFAULT_SETTINGS);
    expect(result.current.lists).toEqual([a]);
    expect(result.current.matched).toBe(2);
    expect(result.current.total).toBe(2);
    expect(result.current.filter).toBeNull();
    expect(frames.size).toBe(0);
  });

  it("filters each list by text and level, and gives the compiled filter", () => {
    const a = [line("a", 0, "GET /health", "info"), line("a", 1, "GET /login", "error")];
    const b = [line("b", 0, "health check", "debug"), line("b", 1, "nothing")];
    const { result } = hook([a, b], { ...DEFAULT_SETTINGS, q: "HEALTH", levels: ["info", "error", "none"] });
    expect(result.current.lists).toEqual([[a[0]], []]);
    expect(result.current.matched).toBe(1);
    expect(result.current.total).toBe(4);
    expect(result.current.filter?.ranges("GET /health")).toEqual([[5, 11]]);
  });

  it("treats an invalid regex from the address as no filter", () => {
    const a = [line("a", 0, "a(")];
    const { result } = hook([a], { ...DEFAULT_SETTINGS, q: "a(", regex: true });
    expect(result.current.filter).toBeNull();
    expect(result.current.lists).toEqual([a]);
  });

  it("tests at most SLICE lines a frame across all lists, until every line is tested", () => {
    const apply = vi.spyOn(FilterCache.prototype, "apply");
    const used = () => apply.mock.results.reduce((sum, r) => sum + (r.value as { used: number }).used, 0);
    const a = lines("a", 6_000);
    const b = lines("b", 6_000);
    const { result } = hook([a, b], { ...DEFAULT_SETTINGS, q: "even" });
    expect(used()).toBe(SLICE);
    expect(frames.size).toBe(1);

    apply.mockClear();
    expect(runFrames()).toBe(1);
    expect(used()).toBe(SLICE);
    expect(frames.size).toBe(1);

    apply.mockClear();
    expect(runFrames()).toBe(1);
    expect(used()).toBe(2_000);
    expect(frames.size).toBe(0);
    expect(result.current.matched).toBe(6_000);
    expect(result.current.total).toBe(12_000);
    expect(result.current.lists[0]).toHaveLength(3_000);
    expect(result.current.lists[1]).toHaveLength(3_000);
  });

  it("starts a fresh cache for a new filter", () => {
    const a = [line("a", 0, "even"), line("a", 1, "odd")];
    const { result, rerender } = hook([a], { ...DEFAULT_SETTINGS, q: "even" });
    expect(result.current.lists).toEqual([[a[0]]]);
    const apply = vi.spyOn(FilterCache.prototype, "apply");
    rerender({ lists: [a], settings: { ...DEFAULT_SETTINGS, q: "odd" } });
    expect(result.current.lists).toEqual([[a[1]]]);
    expect((apply.mock.results.at(-1)?.value as { used: number }).used).toBe(2);
  });

  it("keeps what it tested when the rows grow under the same filter", () => {
    const a = [line("a", 0, "even"), line("a", 1, "odd")];
    const { result, rerender } = hook([a], { ...DEFAULT_SETTINGS, q: "even" });
    const apply = vi.spyOn(FilterCache.prototype, "apply");
    const more = [...a, line("a", 2, "even again")];
    rerender({ lists: [more], settings: { ...DEFAULT_SETTINGS, q: "even" } });
    expect(result.current.lists).toEqual([[a[0], more[2]]]);
    expect((apply.mock.results.at(-1)?.value as { used: number }).used).toBe(1);
  });

  it("forgets the rows the lists no longer hold under the same filter", () => {
    const prune = vi.spyOn(FilterCache.prototype, "prune");
    const a = lines("a", 10);
    const { rerender } = hook([a], { ...DEFAULT_SETTINGS, q: "even" });
    rerender({ lists: [a.slice(8)], settings: { ...DEFAULT_SETTINGS, q: "even" } });
    expect(prune).toHaveBeenLastCalledWith([a.slice(8)]);
    expect((prune.mock.contexts.at(-1) as FilterCache).size).toBe(2);
  });

  it("cancels its frame on unmount", () => {
    const { unmount } = hook([lines("a", SLICE + 10)], { ...DEFAULT_SETTINGS, q: "even" });
    expect(frames.size).toBe(1);
    unmount();
    expect(frames.size).toBe(0);
  });
});
