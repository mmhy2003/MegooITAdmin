import { describe, expect, it } from "vitest";
import { Merger } from "@/lib/logs/merge";
import type { LineRow, MarkerRow, Row } from "@/lib/logs/store";

function line(source: string, seq: number, ms: number): LineRow {
  return {
    kind: "line",
    key: `${source}:0:${seq}`,
    source,
    run: 0,
    seq,
    time: new Date(ms).toISOString(),
    ms,
    text: `${source} ${seq}`,
    plain: `${source} ${seq}`,
    level: "info",
    unit: null,
    truncated: false,
  };
}

function marker(source: string, n: number, ms: number): MarkerRow {
  return { kind: "marker", key: `${source}:m${n}`, source, ms, marker: "skipped", count: 3 };
}

function keys(rows: Row[]): string[] {
  return rows.map((row) => row.key);
}

describe("Merger", () => {
  it("interleaves two sources by time", () => {
    const merger = new Merger();
    const rows = merger.update([
      { id: "a", rows: [line("a", 1, 10), line("a", 2, 30)], trimmed: 0 },
      { id: "b", rows: [line("b", 1, 20), line("b", 2, 40)], trimmed: 0 },
    ]);
    expect(keys(rows)).toEqual(["a:0:1", "b:0:1", "a:0:2", "b:0:2"]);
  });

  it("orders equal times by entry index, then seq, with markers after the lines of the same time", () => {
    const merger = new Merger();
    const rows = merger.update([
      { id: "b", rows: [line("b", 5, 10), marker("b", 1, 10), line("b", 6, 10)], trimmed: 0 },
      { id: "a", rows: [line("a", 2, 10), line("a", 1, 10)], trimmed: 0 },
    ]);
    expect(keys(rows)).toEqual(["b:0:5", "b:0:6", "b:m1", "a:0:1", "a:0:2"]);
  });

  it("inserts a late line at its time", () => {
    const merger = new Merger();
    const a = [line("a", 1, 10), line("a", 2, 50)];
    const b = [line("b", 1, 20)];
    merger.update([
      { id: "a", rows: a, trimmed: 0 },
      { id: "b", rows: b, trimmed: 0 },
    ]);
    const rows = merger.update([
      { id: "a", rows: [...a, line("a", 3, 60)], trimmed: 0 },
      { id: "b", rows: [...b, line("b", 2, 30)], trimmed: 0 },
    ]);
    expect(keys(rows)).toEqual(["a:0:1", "b:0:1", "b:0:2", "a:0:2", "a:0:3"]);
  });

  it("drops the oldest rows of a source when its trimmed count grows", () => {
    const merger = new Merger();
    const a = [line("a", 1, 10), line("a", 2, 30), line("a", 3, 50)];
    const b = [line("b", 1, 20), line("b", 2, 40)];
    merger.update([
      { id: "a", rows: a, trimmed: 0 },
      { id: "b", rows: b, trimmed: 0 },
    ]);
    const rows = merger.update([
      { id: "a", rows: [...a.slice(2), line("a", 4, 60)], trimmed: 2 },
      { id: "b", rows: b, trimmed: 0 },
    ]);
    expect(keys(rows)).toEqual(["b:0:1", "b:0:2", "a:0:3", "a:0:4"]);
  });

  it("removes an entry that is no longer given", () => {
    const merger = new Merger();
    const a = [line("a", 1, 10)];
    merger.update([
      { id: "a", rows: a, trimmed: 0 },
      { id: "b", rows: [line("b", 1, 20)], trimmed: 0 },
    ]);
    expect(keys(merger.update([{ id: "a", rows: a, trimmed: 0 }]))).toEqual(["a:0:1"]);
  });

  it("returns the same array when nothing is new", () => {
    const merger = new Merger();
    const entries = [
      { id: "a", rows: [line("a", 1, 10)], trimmed: 0 },
      { id: "b", rows: [line("b", 1, 20)], trimmed: 0 },
    ];
    const first = merger.update(entries);
    expect(merger.update(entries)).toBe(first);
    expect(merger.update(entries.map((entry) => ({ ...entry, rows: [...entry.rows] })))).toBe(first);
    const next = merger.update([entries[0], { ...entries[1], rows: [...entries[1].rows, line("b", 2, 30)] }]);
    expect(next).not.toBe(first);
    expect(keys(first)).toEqual(["a:0:1", "b:0:1"]);
  });

  it("orders again when the entries change order", () => {
    const merger = new Merger();
    const a = { id: "a", rows: [line("a", 1, 10)], trimmed: 0 };
    const b = { id: "b", rows: [line("b", 1, 10)], trimmed: 0 };
    expect(keys(merger.update([a, b]))).toEqual(["a:0:1", "b:0:1"]);
    expect(keys(merger.update([b, a]))).toEqual(["b:0:1", "a:0:1"]);
  });
});
