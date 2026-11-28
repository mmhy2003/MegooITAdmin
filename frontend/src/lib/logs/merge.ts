import type { Row } from "@/lib/logs/store";

export type MergeEntry = { id: string; rows: Row[]; trimmed: number };

/** What the merger holds of one entry: its rows in arrival order, and how many rows it has had in all. */
type Held = { rows: Row[]; seen: number };

/**
 * The rows of several entries in one list, ordered by time, then by the entry's index, then by seq. Markers come after
 * the lines of their entry with the same time. Each update adds only the rows that are new since the last one.
 */
export class Merger {
  private held = new Map<string, Held>();
  private order: string[] = [];
  private merged: Row[] = [];
  private owner = new Map<Row, string>();

  update(entries: MergeEntry[]): Row[] {
    const ids = entries.map((entry) => entry.id);
    const index = new Map(ids.map((id, i) => [id, i]));
    const removed = new Set<Row>();
    for (const [id, held] of this.held) {
      if (index.has(id)) continue;
      for (const row of held.rows) removed.add(row);
      this.held.delete(id);
    }
    const added: Row[] = [];
    for (const entry of entries) {
      let held = this.held.get(entry.id);
      // Not fed while the source was removed and added again: the entry is a new one, so its old rows go.
      if (held !== undefined && !continues(held, entry)) {
        for (const row of held.rows) removed.add(row);
        held = undefined;
      }
      held ??= { rows: [], seen: entry.trimmed };
      this.held.set(entry.id, held);
      const dropped = Math.min(Math.max(0, entry.trimmed - (held.seen - held.rows.length)), held.rows.length);
      for (const row of held.rows.splice(0, dropped)) removed.add(row);
      const total = entry.trimmed + entry.rows.length;
      for (const row of entry.rows.slice(Math.max(0, entry.rows.length - (total - held.seen)))) {
        held.rows.push(row);
        added.push(row);
        this.owner.set(row, entry.id);
      }
      held.seen = Math.max(held.seen, total);
    }
    const kept = this.order.filter((id) => index.has(id));
    const reordered = kept.some((id, i) => i > 0 && index.get(id)! < index.get(kept[i - 1])!);
    this.order = ids;
    if (removed.size === 0 && added.length === 0 && !reordered) return this.merged;

    for (const row of removed) this.owner.delete(row);
    const rank = (row: Row) => index.get(this.owner.get(row)!)!;
    const order = (a: Row, b: Row) => compare(a, b, rank(a), rank(b));
    const next = removed.size > 0 ? this.merged.filter((row) => !removed.has(row)) : [...this.merged];
    if (reordered) {
      next.push(...added);
      next.sort(order);
    } else {
      for (const row of added) next.splice(insertAt(next, row, order), 0, row);
    }
    this.merged = next;
    return next;
  }
}

/** Whether `entry` is the one `held` was taken from: it has had as many rows, and holds the last one at its place. */
function continues(held: Held, entry: MergeEntry): boolean {
  if (entry.trimmed + entry.rows.length < held.seen) return false;
  const last = held.rows[held.rows.length - 1];
  const at = held.seen - 1 - entry.trimmed;
  return last === undefined || at < 0 || entry.rows[at] === last;
}

function compare(a: Row, b: Row, ia: number, ib: number): number {
  if (a.ms !== b.ms) return a.ms - b.ms;
  if (ia !== ib) return ia - ib;
  if (a.kind !== b.kind) return a.kind === "line" ? -1 : 1;
  if (a.kind === "line" && b.kind === "line") return a.seq - b.seq;
  return 0;
}

/** Where `row` goes: after every row that is not after it. Most rows are newest, so the end is checked first. */
function insertAt(rows: Row[], row: Row, order: (a: Row, b: Row) => number): number {
  if (rows.length === 0 || order(row, rows[rows.length - 1]) >= 0) return rows.length;
  let low = 0;
  let high = rows.length - 1;
  while (low < high) {
    const mid = (low + high) >> 1;
    if (order(row, rows[mid]) < 0) high = mid;
    else low = mid + 1;
  }
  return low;
}
