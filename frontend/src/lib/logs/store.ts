import { stripAnsi } from "@/lib/logs/ansi";
import { levelOf, type LevelGroup } from "@/lib/logs/levels";
import type { ServerMessage, WireLine } from "@/lib/logs/socket";
import { encodeSource, sameSource, type LogSource } from "@/lib/logs/sources";

export type LineRow = {
  kind: "line";
  key: string;
  source: string;
  run: number;
  seq: number;
  time: string;
  ms: number;
  text: string;
  plain: string;
  level: LevelGroup;
  unit: string | null;
  truncated: boolean;
};
export type MarkerRow = {
  kind: "marker";
  key: string;
  source: string;
  ms: number;
  marker: "skipped" | "reconnected";
  count: number;
};
export type Row = LineRow | MarkerRow;
export type PaneState =
  | { state: "opening" }
  | { state: "live" }
  /** `at`: epoch ms of the next try. */
  | { state: "retrying"; reason: string; attempt: number; at: number }
  /** Waits for "Reconnect". */
  | { state: "ended"; reason: string; status: number | null }
  | { state: "denied"; reason: string }
  | { state: "idle" };
export type SourceEntry = {
  id: string;
  source: LogSource;
  rows: Row[];
  trimmed: number;
  state: PaneState;
  skipped: number;
  retries: number;
  wireId: string | null;
  run: number;
};
export type SocketState = "connecting" | "live" | "reconnecting";
export type StoreSnapshot = { version: number; entries: SourceEntry[]; socket: SocketState; idle: boolean };

/** A source keeps its last MAX_ROWS rows; older ones go TRIM_BLOCK at a time, so a trim is not paid per line. */
export const MAX_ROWS = 10_000;
export const TRIM_BLOCK = 1_000;

export type LogStoreOptions = {
  /** Called with the sources to subscribe to, each time that list changes. */
  onWanted: (sources: LogSource[]) => void;
  frame?: (cb: () => void) => void;
  now?: () => number;
};

/**
 * Each followed source's rows and state, kept outside React. Takes the socket's messages and tells its listeners at
 * most once per frame; `snapshot()` is the same object until then, as `useSyncExternalStore` needs.
 */
export class LogStore {
  readonly #onWanted: (sources: LogSource[]) => void;
  readonly #frame: (cb: () => void) => void;
  readonly #now: () => number;
  #entries: SourceEntry[] = [];
  #reported: string[] = [];
  #socket: SocketState = "connecting";
  #markers = 0;
  #listeners = new Set<() => void>();
  /** The ids of the entries changed since the last snapshot, and whether anything changed at all. */
  #changed = new Set<string>();
  #dirty = false;
  #pending = false;
  #disposed = false;
  #snapshot: StoreSnapshot;

  constructor(options: LogStoreOptions) {
    this.#onWanted = options.onWanted;
    this.#frame = options.frame ?? ((cb) => requestAnimationFrame(cb));
    this.#now = options.now ?? Date.now;
    this.#snapshot = { version: 0, entries: [], socket: this.#socket, idle: false };
  }

  /** Follow these sources, in this order: kept ones keep their rows, new ones open. */
  setSources(sources: LogSource[]): void {
    const kept = new Map(this.#entries.map((entry) => [entry.id, entry]));
    const next: SourceEntry[] = [];
    for (const source of sources) {
      const id = encodeSource(source);
      if (next.some((entry) => entry.id === id)) continue;
      const entry = kept.get(id) ?? {
        id,
        source,
        rows: [],
        trimmed: 0,
        state: { state: "opening" },
        skipped: 0,
        retries: 0,
        wireId: null,
        run: 0,
      };
      if (!kept.has(id)) this.#touch(entry);
      next.push(entry);
    }
    this.#entries = next;
    this.#dirty = true;
    this.#schedule();
    this.#changedWanted();
  }

  /** The sources to subscribe to: those opening or live. */
  wanted(): LogSource[] {
    return this.#entries
      .filter((entry) => entry.state.state === "opening" || entry.state.state === "live")
      .map((entry) => entry.source);
  }

  handle(message: ServerMessage): void {
    switch (message.type) {
      case "subscribed":
        this.#subscribed(message);
        break;
      case "lines": {
        const entry = this.#byWire(message.source);
        if (entry === undefined) return;
        if (message.backlog) this.#backlog(entry, message.lines);
        else this.#addLines(entry, message.lines);
        this.#trim(entry);
        this.#touch(entry);
        break;
      }
      case "skipped": {
        const entry = this.#byWire(message.source);
        if (entry === undefined) return;
        this.#addMarker(entry, "skipped", message.count);
        entry.skipped += message.count;
        this.#trim(entry);
        this.#touch(entry);
        break;
      }
    }
    this.#changedWanted();
  }

  subscribe(listener: () => void): () => void {
    this.#listeners.add(listener);
    return () => this.#listeners.delete(listener);
  }

  snapshot(): StoreSnapshot {
    return this.#snapshot;
  }

  /** Stops notifying: a frame already asked for does nothing. */
  dispose(): void {
    this.#disposed = true;
    this.#listeners.clear();
  }

  #subscribed(message: Extract<ServerMessage, { type: "subscribed" }>): void {
    for (const entry of this.#entries) {
      if (entry.state.state !== "opening" && entry.state.state !== "live") continue;
      const match = message.sources.find((s) => sameSource(entry.source, s.source));
      if (match !== undefined) {
        if (entry.wireId !== match.id) this.#touch(entry);
        entry.wireId = match.id;
        continue;
      }
      const denied = message.denied.find((d) => sameSource(entry.source, d.source));
      if (denied !== undefined) {
        entry.state = { state: "denied", reason: denied.reason };
        entry.wireId = null;
        this.#touch(entry);
      }
    }
  }

  /** A backlog continues the rows when it holds the last line row; otherwise it starts a new run after a marker. */
  #backlog(entry: SourceEntry, lines: WireLine[]): void {
    const last = entry.rows.findLast((row): row is LineRow => row.kind === "line");
    if (last === undefined) {
      this.#addLines(entry, lines);
    } else {
      const at = lines.findIndex((l) => l.seq === last.seq && l.time === last.time && l.text === last.text);
      if (at >= 0) {
        this.#addLines(entry, lines.slice(at + 1));
      } else {
        this.#addMarker(entry, "reconnected", 0);
        entry.run += 1;
        this.#addLines(entry, lines);
      }
    }
    entry.state = { state: "live" };
    entry.retries = 0;
  }

  #addLines(entry: SourceEntry, lines: WireLine[]): void {
    for (const line of lines) {
      const plain = stripAnsi(line.text);
      entry.rows.push({
        kind: "line",
        key: `${entry.id}:${entry.run}:${line.seq}`,
        source: entry.id,
        run: entry.run,
        seq: line.seq,
        time: line.time,
        ms: Date.parse(line.time),
        text: line.text,
        plain,
        level: levelOf(line.level, plain),
        unit: line.unit ?? null,
        truncated: line.truncated ?? false,
      });
    }
  }

  #addMarker(entry: SourceEntry, marker: MarkerRow["marker"], count: number): void {
    const last = entry.rows[entry.rows.length - 1];
    this.#markers += 1;
    entry.rows.push({
      kind: "marker",
      key: `${entry.id}:m${this.#markers}`,
      source: entry.id,
      ms: last?.ms ?? this.#now(),
      marker,
      count,
    });
  }

  #trim(entry: SourceEntry): void {
    if (entry.rows.length <= MAX_ROWS) return;
    const drop = Math.max(TRIM_BLOCK, entry.rows.length - MAX_ROWS);
    entry.rows.splice(0, drop);
    entry.trimmed += drop;
  }

  #byWire(wireId: string): SourceEntry | undefined {
    return this.#entries.find((entry) => entry.wireId === wireId);
  }

  #changedWanted(): void {
    const wanted = this.wanted();
    const ids = wanted.map(encodeSource);
    if (ids.length === this.#reported.length && ids.every((id, i) => id === this.#reported[i])) return;
    this.#reported = ids;
    this.#onWanted(wanted);
  }

  /** Mark an entry changed and ask for one frame. */
  #touch(entry: SourceEntry): void {
    this.#changed.add(entry.id);
    this.#dirty = true;
    this.#schedule();
  }

  #schedule(): void {
    if (this.#pending || this.#disposed) return;
    this.#pending = true;
    this.#frame(() => this.#flush());
  }

  #flush(): void {
    this.#pending = false;
    if (this.#disposed || !this.#dirty) return;
    const previous = new Map(this.#snapshot.entries.map((entry) => [entry.id, entry]));
    // A changed entry is published as a copy, so React sees new rows; the others keep their identity.
    const entries = this.#entries.map((entry) => {
      const before = previous.get(entry.id);
      return before !== undefined && !this.#changed.has(entry.id) ? before : { ...entry, rows: entry.rows.slice() };
    });
    this.#changed.clear();
    this.#dirty = false;
    this.#snapshot = {
      version: this.#snapshot.version + 1,
      entries,
      socket: this.#socket,
      idle: entries.length > 0 && entries.every((entry) => entry.state.state === "idle"),
    };
    for (const listener of this.#listeners) listener();
  }
}
