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
