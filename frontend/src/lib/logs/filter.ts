import type { LevelGroup } from "@/lib/logs/levels";
import type { Row } from "@/lib/logs/store";

export type CompiledFilter = { test: (plain: string) => boolean; ranges: (plain: string) => [number, number][] };

/** Lines tested per frame while a new filter works through what a pane holds. */
export const SLICE = 5_000;

function escape(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function build(source: string): RegExp {
  try {
    return new RegExp(source, "giu");
  } catch {
    return new RegExp(source, "gi");
  }
}

/** The filter of `q`: text matched literally, or a regex. Both ignore case. */
export function compileFilter(q: string, regex: boolean): CompiledFilter | null | { error: "invalid_regex" } {
  if (q === "") return null;
  let pattern: RegExp;
  try {
    pattern = build(regex ? q : escape(q));
  } catch {
    return { error: "invalid_regex" };
  }
  return {
    test(plain) {
      pattern.lastIndex = 0;
      return pattern.test(plain);
    },
    ranges(plain) {
      const found: [number, number][] = [];
      pattern.lastIndex = 0;
      let match: RegExpExecArray | null;
      while ((match = pattern.exec(plain)) !== null) {
        if (match[0].length === 0) {
          pattern.lastIndex += 1;
          continue;
        }
        found.push([match.index, match.index + match[0].length]);
      }
      return found;
    },
  };
}

/** Remembers, per row key, whether a line matches the filter, so each line is tested once. */
export class FilterCache {
  private readonly matches = new Map<string, boolean>();

  constructor(private readonly filter: CompiledFilter | null) {}

  apply(
    rows: Row[],
    levels: ReadonlySet<LevelGroup>,
    budget: number,
  ): { rows: Row[]; matched: number; total: number; pending: boolean; used: number } {
    const kept: boolean[] = new Array<boolean>(rows.length);
    let matched = 0;
    let total = 0;
    let pending = false;
    let used = 0;
    for (let i = rows.length - 1; i >= 0; i--) {
      const row = rows[i];
      if (row.kind === "marker") {
        kept[i] = true;
        continue;
      }
      total += 1;
      kept[i] = false;
      if (!levels.has(row.level)) continue;
      let match = true;
      if (this.filter) {
        const cached = this.matches.get(row.key);
        if (cached !== undefined) {
          match = cached;
        } else if (used < budget) {
          match = this.filter.test(row.plain);
          this.matches.set(row.key, match);
          used += 1;
        } else {
          pending = true;
          continue;
        }
      }
      if (match) {
        kept[i] = true;
        matched += 1;
      }
    }
    return { rows: rows.filter((_, i) => kept[i]), matched, total, pending, used };
  }
}
