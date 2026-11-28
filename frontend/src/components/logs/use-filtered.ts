"use client";

import { useEffect, useMemo, useState } from "react";
import { compileFilter, FilterCache, SLICE, type CompiledFilter } from "@/lib/logs/filter";
import type { LevelGroup } from "@/lib/logs/levels";
import type { ViewSettings } from "@/lib/logs/sources";
import type { Row } from "@/lib/logs/store";

type Filtered = { lists: Row[][]; matched: number; total: number; filter: CompiledFilter | null };

/**
 * The rows of each list that pass the settings' filter and levels, with the lines matched and held across all lists.
 * A new filter works through what the lists hold in slices: at most SLICE untested lines a frame across all lists,
 * newest first, and another frame while some are left. An invalid regex (from the address) filters nothing.
 */
export function useFiltered(lists: Row[][], settings: ViewSettings): Filtered {
  const { q, regex } = settings;
  const filter = useMemo(() => {
    const compiled = compileFilter(q, regex);
    return compiled && "error" in compiled ? null : compiled;
  }, [q, regex]);
  // One cache per filter: a new filter tests every line again, the same one only the lines that came since.
  const cache = useMemo(() => new FilterCache(filter), [filter]);
  const levelsKey = settings.levels.join(",");
  // No levels on gives an empty set, not one holding "".
  const levels = useMemo(
    () => new Set(levelsKey === "" ? [] : (levelsKey.split(",") as LevelGroup[])),
    [levelsKey],
  );
  // A tick, bumped by each frame while lines are left to test: its value is never read, but as a dependency of the
  // memo below it makes the next slice run.
  const [frame, setFrame] = useState(0);

  const result = useMemo(() => {
    void frame; // only a dependency: see `frame` above
    let budget = SLICE;
    let matched = 0;
    let total = 0;
    let pending = false;
    const filtered: Row[][] = [];
    for (const rows of lists) {
      const applied = cache.apply(rows, levels, budget);
      budget -= applied.used;
      matched += applied.matched;
      total += applied.total;
      pending ||= applied.pending;
      filtered.push(applied.rows);
    }
    return { lists: filtered, matched, total, pending };
  }, [lists, levels, cache, frame]);

  useEffect(() => {
    if (!result.pending) return;
    const id = requestAnimationFrame(() => setFrame((n) => n + 1));
    return () => cancelAnimationFrame(id);
  }, [result]);

  return { lists: result.lists, matched: result.matched, total: result.total, filter };
}
