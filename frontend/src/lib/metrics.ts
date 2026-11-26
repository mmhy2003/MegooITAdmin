import type { Monitoring, Server } from "@/lib/servers";

export const RANGES = ["live", "1h", "6h", "24h", "7d", "30d", "1y"] as const;
export type RangeName = (typeof RANGES)[number];
export const RANGE_LABELS: Record<RangeName, string> = {
  live: "Live",
  "1h": "1 hour",
  "6h": "6 hours",
  "24h": "24 hours",
  "7d": "7 days",
  "30d": "30 days",
  "1y": "1 year",
};
/** A percentage turns amber from here and pink from PINK_FROM: a visual hint, not an alert. */
export const AMBER_FROM = 80;
export const PINK_FROM = 90;
/** How far back the live charts reach, and how often a historical range is read again. */
export const LIVE_WINDOW_MS = 15 * 60_000;
export const HISTORY_REFRESH_MS = 60_000;
/** The trend of a card: 60 slots of 5 seconds, the last five minutes. */
export const TREND_SLOTS = 60;
export const TREND_STEP_MS = 5_000;
/** Values older than this are shown as stale. */
export const STALE_AFTER_MS = 5 * 60_000;
export type Tone = "normal" | "amber" | "pink";
export type Disk = { mount: string; percent: number };
/** The six numbers of a server's newest sample; each is null when the sample did not have it. */
export type Overview = {
  server_id: string;
  time: string | null;
  cpu: number | null;
  mem: number | null;
  load: number | null;
  disk: Disk | null;
  rx: number | null;
  tx: number | null;
};
/** `start` is the time of slot 0 in milliseconds. */
export type Trend = { start: number; cpu: (number | null)[]; mem: (number | null)[] };
export type ServerOverviewRead = Overview & { trend: { start: string; cpu: (number | null)[]; mem: (number | null)[] } };
/** The body of GET /api/metrics/overview. */
export type OverviewRead = { servers: ServerOverviewRead[]; denied: string[] };
export type Vitals = { overview: Overview; trend: Trend };
export type Reading = [metric: string, instance: string, value: number];
export type OverviewMessage = Overview & { type: "overview"; time: string };
export type SampleMessage = { type: "sample"; server_id: string; time: string; readings: Reading[] };
export type SubscribedMessage = { type: "subscribed"; server_ids: string[]; denied: string[] };
export type ErrorMessage = { type: "error"; detail: string };
export type LiveMessage = OverviewMessage | SampleMessage | SubscribedMessage | ErrorMessage;
/** One line of a chart; `min` and `max` are null for raw samples. */
export type Series = {
  metric: string;
  instance: string;
  time: string[];
  avg: number[];
  min: (number | null)[];
  max: (number | null)[];
};
/** The body of GET /api/servers/{id}/metrics; `step_seconds` is null for raw samples. */
export type SeriesAnswer = { range: RangeName; step_seconds: number | null; start: string; end: string; series: Series[] };
export type ChartLine = { key: string; label: string; color: string; series: Series; band: boolean };
export type ChartRow = { t: number } & Record<string, number | null | [number, number]>;

const DASH = "—";
const BYTE_UNITS = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"];

/** The range in the address; an unknown or missing one is live. */
export function rangeFrom(params: URLSearchParams): RangeName {
  const range = params.get("range");
  return (RANGES as readonly string[]).includes(range ?? "") ? (range as RangeName) : "live";
}

/** A whole percent: "42%". */
export function formatPercent(v: number | null): string {
  return v === null ? DASH : `${Math.round(v)}%`;
}

/** Binary units: one decimal under 10, none from 10. Bytes are always whole. */
export function formatBytes(v: number | null): string {
  if (v === null) return DASH;
  let value = v;
  let unit = 0;
  while (Math.abs(value) >= 1024 && unit < BYTE_UNITS.length - 1) {
    value /= 1024;
    unit += 1;
  }
  if (unit === 0) return `${Math.round(value)} B`;
  const tenth = Math.round(value * 10) / 10;
  const text = Math.abs(tenth) < 10 ? tenth.toFixed(1) : String(Math.round(value));
  return `${text} ${BYTE_UNITS[unit]}`;
}

/** Bytes per second: "2.0 KiB/s". */
export function formatRate(v: number | null): string {
  return v === null ? DASH : `${formatBytes(v)}/s`;
}

/** A load average with two decimals: "0.50". */
export function formatLoad(v: number | null): string {
  return v === null ? DASH : v.toFixed(2);
}

/** Pink from PINK_FROM, amber from AMBER_FROM, otherwise normal. */
export function toneOf(percent: number | null): Tone {
  if (percent === null) return "normal";
  if (percent >= PINK_FROM) return "pink";
  if (percent >= AMBER_FROM) return "amber";
  return "normal";
}

function fleetRank(monitoring: Monitoring | null): number {
  if (monitoring?.state === "unreachable") return 0;
  if (monitoring?.state === "reachable") return 1;
  return 2;
}

/** Unreachable servers first, then reachable ones, then the rest; each by name. Returns a new list. */
export function fleetOrder<T extends { name: string; monitoring: Monitoring | null }>(servers: T[]): T[] {
  return [...servers].sort(
    (a, b) => fleetRank(a.monitoring) - fleetRank(b.monitoring) || a.name.localeCompare(b.name),
  );
}

/** How many servers are in each monitoring state; `notChecked` has no state yet. */
export function fleetCounts(servers: Server[]): {
  total: number;
  reachable: number;
  unreachable: number;
  notMonitored: number;
  notChecked: number;
} {
  const counts = { total: servers.length, reachable: 0, unreachable: 0, notMonitored: 0, notChecked: 0 };
  for (const { monitoring } of servers) {
    if (monitoring === null) counts.notChecked += 1;
    else if (monitoring.state === "reachable") counts.reachable += 1;
    else if (monitoring.state === "unreachable") counts.unreachable += 1;
    else counts.notMonitored += 1;
  }
  return counts;
}

/** The slot a time falls in, counted from the trend's start. */
function slotOf(start: number, timeMs: number): number {
  return Math.floor((timeMs - start) / TREND_STEP_MS);
}

/** Sixty empty slots whose last one holds `endMs`. */
export function emptyTrend(endMs: number): Trend {
  const start = endMs - (endMs % TREND_STEP_MS) - (TREND_SLOTS - 1) * TREND_STEP_MS;
  return { start, cpu: Array(TREND_SLOTS).fill(null), mem: Array(TREND_SLOTS).fill(null) };
}

/** The trend of GET /api/metrics/overview, with its start in milliseconds. */
export function trendOf(read: ServerOverviewRead["trend"]): Trend {
  return { start: Date.parse(read.start), cpu: [...read.cpu], mem: [...read.mem] };
}

function shifted(values: (number | null)[], by: number): (number | null)[] {
  return [...values.slice(Math.min(by, TREND_SLOTS)), ...Array(Math.min(by, TREND_SLOTS)).fill(null)];
}

/** Puts a sample into its slot, moving the window on when the slot is past the last one. A null keeps the slot's
 * value, and a time before the window is ignored. */
export function pushTrend(trend: Trend, timeMs: number, cpu: number | null, mem: number | null): Trend {
  const slot = slotOf(trend.start, timeMs);
  if (slot < 0) return trend;
  const by = Math.max(0, slot - (TREND_SLOTS - 1));
  const next = {
    start: trend.start + by * TREND_STEP_MS,
    cpu: shifted(trend.cpu, by),
    mem: shifted(trend.mem, by),
  };
  const at = slot - by;
  if (cpu !== null) next.cpu[at] = cpu;
  if (mem !== null) next.mem[at] = mem;
  return next;
}

/** A server of GET /api/metrics/overview as the cards keep it. */
export function vitalsOf(read: ServerOverviewRead): Vitals {
  const { trend, ...overview } = read;
  return { overview, trend: trendOf(trend) };
}

/** The next overview, where each value it lacks keeps the previous one. */
export function mergeOverview(previous: Overview | null, next: Overview): Overview {
  if (previous === null) return next;
  return {
    server_id: next.server_id,
    time: next.time ?? previous.time,
    cpu: next.cpu ?? previous.cpu,
    mem: next.mem ?? previous.mem,
    load: next.load ?? previous.load,
    disk: next.disk ?? previous.disk,
    rx: next.rx ?? previous.rx,
    tx: next.tx ?? previous.tx,
  };
}

/** A live overview message merged into a server's vitals; without vitals the trend starts empty. */
export function applyMessage(previous: Vitals | undefined, message: OverviewMessage): Vitals {
  const { server_id, time, cpu, mem, load, disk, rx, tx } = message;
  const timeMs = Date.parse(time);
  const trend = previous?.trend ?? emptyTrend(timeMs);
  return {
    overview: mergeOverview(previous?.overview ?? null, { server_id, time, cpu, mem, load, disk, rx, tx }),
    trend: pushTrend(trend, timeMs, message.cpu, message.mem),
  };
}

/** True when there is no time, or it is older than STALE_AFTER_MS. */
export function isStale(time: string | null, nowMs: number): boolean {
  return time === null || nowMs - Date.parse(time) > STALE_AFTER_MS;
}

function windowed(series: Series, fromMs: number): Series {
  const first = series.time.findIndex((t) => Date.parse(t) >= fromMs);
  const from = first === -1 ? series.time.length : first;
  if (from === 0) return series;
  return {
    ...series,
    time: series.time.slice(from),
    avg: series.avg.slice(from),
    min: series.min.slice(from),
    max: series.max.slice(from),
  };
}

/** A live sample appended to the live series of the given metrics; a new instance starts a series after the others.
 * Points older than the sample's time minus `windowMs` are dropped. */
export function appendSample(series: Series[], sample: SampleMessage, metrics: string[], windowMs: number): Series[] {
  const next = series.map((s) => ({ ...s, time: [...s.time], avg: [...s.avg], min: [...s.min], max: [...s.max] }));
  for (const [metric, instance, value] of sample.readings) {
    if (!metrics.includes(metric)) continue;
    let target = next.find((s) => s.metric === metric && s.instance === instance);
    if (target === undefined) {
      target = { metric, instance, time: [], avg: [], min: [], max: [] };
      next.push(target);
    }
    target.time.push(sample.time);
    target.avg.push(value);
    target.min.push(null);
    target.max.push(null);
  }
  const fromMs = Date.parse(sample.time) - windowMs;
  return next.map((s) => windowed(s, fromMs));
}

/** One series that adds up the averages of all of them at every time any of them has. */
export function sumSeries(series: Series[], metric: string, instance: string): Series {
  const sums = new Map<number, { time: string; value: number }>();
  for (const s of series) {
    s.time.forEach((time, i) => {
      const t = Date.parse(time);
      const sum = sums.get(t);
      if (sum === undefined) sums.set(t, { time, value: s.avg[i] });
      else sum.value += s.avg[i];
    });
  }
  const points = [...sums.entries()].sort(([a], [b]) => a - b).map(([, point]) => point);
  return {
    metric,
    instance,
    time: points.map((p) => p.time),
    avg: points.map((p) => p.value),
    min: points.map(() => null),
    max: points.map(() => null),
  };
}

/** The rows of a chart: one per time of any line, sorted. Where two times are more than three steps apart, a row
 * with every key null sits between them so the lines break. */
export function chartRows(lines: ChartLine[], stepMs: number): ChartRow[] {
  const keys = lines.flatMap((line) => (line.band ? [line.key, `${line.key}_band`] : [line.key]));
  const rows = new Map<number, ChartRow>();
  const rowAt = (t: number): ChartRow => {
    let row = rows.get(t);
    if (row === undefined) {
      row = { t } as ChartRow;
      for (const key of keys) row[key] = null;
      rows.set(t, row);
    }
    return row;
  };
  for (const { key, series, band } of lines) {
    series.time.forEach((time, i) => {
      const row = rowAt(Date.parse(time));
      row[key] = series.avg[i];
      const min = series.min[i];
      const max = series.max[i];
      if (band && min !== null && max !== null) row[`${key}_band`] = [min, max];
    });
  }
  const sorted = [...rows.values()].sort((a, b) => a.t - b.t);
  const result: ChartRow[] = [];
  sorted.forEach((row, i) => {
    const before = sorted[i - 1];
    if (before !== undefined && row.t - before.t > 3 * stepMs) {
      const gap = { t: (before.t + row.t) / 2 } as ChartRow;
      for (const key of keys) gap[key] = null;
      result.push(gap);
    }
    result.push(row);
  });
  return result;
}

/** The newest average of a series, or null. */
export function lastValue(series: Series | undefined): number | null {
  return series?.avg.at(-1) ?? null;
}

/** The series of a metric and instance in an answer. */
export function seriesOf(answer: SeriesAnswer | null, metric: string, instance = ""): Series | undefined {
  return answer?.series.find((s) => s.metric === metric && s.instance === instance);
}

/** The instances of a metric in an answer, sorted, without the empty one. */
export function instancesOf(answer: SeriesAnswer | null, metric: string): string[] {
  return (answer?.series ?? [])
    .filter((s) => s.metric === metric && s.instance !== "")
    .map((s) => s.instance)
    .sort();
}
