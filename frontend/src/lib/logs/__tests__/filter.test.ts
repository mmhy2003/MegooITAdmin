import { describe, expect, it } from "vitest";
import { compileFilter, FilterCache, type CompiledFilter } from "@/lib/logs/filter";
import type { LevelGroup } from "@/lib/logs/levels";
import type { LineRow, MarkerRow, Row } from "@/lib/logs/store";

function compiled(q: string, regex: boolean): CompiledFilter {
  const filter = compileFilter(q, regex);
  if (filter === null || "error" in filter) throw new Error(`no filter for ${q}`);
  return filter;
}

function line(seq: number, plain: string, level: LevelGroup = "info"): LineRow {
  return {
    kind: "line",
    key: `a:0:${seq}`,
    source: "a",
    run: 0,
    seq,
    time: "2026-11-28T09:00:00Z",
    ms: 0,
    text: plain,
    plain,
    level,
    unit: null,
    truncated: false,
  };
}

function marker(n: number): MarkerRow {
  return { kind: "marker", key: `a:m${n}`, source: "a", ms: 0, marker: "skipped", count: 3 };
}

const ALL: ReadonlySet<LevelGroup> = new Set<LevelGroup>(["error", "warning", "info", "debug", "none"]);

describe("compileFilter", () => {
  it("gives no filter for an empty query", () => {
    expect(compileFilter("", false)).toBeNull();
    expect(compileFilter("", true)).toBeNull();
  });

  it("matches text without regard to case and takes it literally", () => {
    const filter = compiled("Fail.*", false);
    expect(filter.test("job FAIL.* now")).toBe(true);
    expect(filter.test("job failed now")).toBe(false);
  });

  it("matches a regex without regard to case", () => {
    const filter = compiled("err(or)?\\b", true);
    expect(filter.test("an ERROR here")).toBe(true);
    expect(filter.test("no problem")).toBe(false);
  });

  it("reports an invalid regex", () => {
    expect(compileFilter("(", true)).toEqual({ error: "invalid_regex" });
  });

  it("gives the range of every match, without overlap", () => {
    expect(compiled("ab", false).ranges("ab xAB abab")).toEqual([
      [0, 2],
      [4, 6],
      [7, 9],
      [9, 11],
    ]);
    expect(compiled("aa", true).ranges("aaaa")).toEqual([
      [0, 2],
      [2, 4],
    ]);
  });

  it("gives no empty range for a zero-width regex", () => {
    expect(compiled("^", true).ranges("abc")).toEqual([]);
    expect(compiled("x*", true).ranges("axxb")).toEqual([[1, 3]]);
  });

  it("gives the same answer on every call", () => {
    const filter = compiled("a", true);
    expect(filter.test("a")).toBe(true);
    expect(filter.test("a")).toBe(true);
    expect(filter.test("ba")).toBe(true);
  });
});

describe("FilterCache.apply", () => {
  it("passes markers whatever the levels and the filter", () => {
    const rows: Row[] = [marker(1), line(1, "nothing")];
    const result = new FilterCache(compiled("zzz", false)).apply(rows, new Set(), 100);
    expect(result.rows).toEqual([marker(1)]);
  });

  it("passes a line only when its level is on and the filter matches", () => {
    const rows: Row[] = [line(1, "disk error", "error"), line(2, "disk ok", "info"), line(3, "disk warn", "warning")];
    const result = new FilterCache(compiled("disk", false)).apply(rows, new Set<LevelGroup>(["error", "info"]), 100);
    expect(result.rows.map((r) => r.key)).toEqual(["a:0:1", "a:0:2"]);

    const narrowed = new FilterCache(compiled("error", false)).apply(rows, ALL, 100);
    expect(narrowed.rows.map((r) => r.key)).toEqual(["a:0:1"]);
  });

  it("passes every line whose level is on when there is no filter", () => {
    const rows: Row[] = [line(1, "a", "debug"), line(2, "b", "none")];
    const result = new FilterCache(null).apply(rows, new Set<LevelGroup>(["none"]), 0);
    expect(result).toEqual({ rows: [rows[1]], matched: 1, total: 2, pending: false, used: 0 });
  });

  it("tests the newest uncached lines first, within the budget", () => {
    const rows: Row[] = [line(1, "hit"), line(2, "hit"), marker(1), line(3, "miss"), line(4, "hit")];
    const cache = new FilterCache(compiled("hit", false));

    const first = cache.apply(rows, ALL, 2);
    expect(first.rows.map((r) => r.key)).toEqual(["a:m1", "a:0:4"]);
    expect(first.pending).toBe(true);
    expect(first.used).toBe(2);

    const second = cache.apply(rows, ALL, 2);
    expect(second.rows.map((r) => r.key)).toEqual(["a:0:1", "a:0:2", "a:m1", "a:0:4"]);
    expect(second.pending).toBe(false);
    expect(second.used).toBe(2);
  });

  it("tests nothing again for the same rows", () => {
    const rows: Row[] = [line(1, "hit"), line(2, "miss")];
    const cache = new FilterCache(compiled("hit", false));
    cache.apply(rows, ALL, 100);

    const again = cache.apply(rows, ALL, 100);
    expect(again.used).toBe(0);
    expect(again.pending).toBe(false);
    expect(again.rows.map((r) => r.key)).toEqual(["a:0:1"]);
  });

  it("counts line rows only in matched and total", () => {
    const rows: Row[] = [marker(1), line(1, "hit"), line(2, "miss"), marker(2), line(3, "hit", "debug")];
    const result = new FilterCache(compiled("hit", false)).apply(rows, new Set<LevelGroup>(["info"]), 100);
    expect(result.matched).toBe(1);
    expect(result.total).toBe(3);
  });
});
