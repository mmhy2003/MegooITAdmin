import type { Row } from "@/lib/logs/store";

const MAX_SLUG = 40;

function pad(n: number, width = 2): string {
  return String(n).padStart(width, "0");
}

/** The parts of `ms` in UTC or in the viewer's time zone. */
function fields(ms: number, utc: boolean) {
  const d = new Date(ms);
  if (utc) {
    return { y: d.getUTCFullYear(), mo: d.getUTCMonth() + 1, d: d.getUTCDate(), h: d.getUTCHours(),
      mi: d.getUTCMinutes(), s: d.getUTCSeconds() };
  }
  return { y: d.getFullYear(), mo: d.getMonth() + 1, d: d.getDate(), h: d.getHours(), mi: d.getMinutes(),
    s: d.getSeconds() };
}

/** "HH:MM:SS.mmm" */
export function clock(ms: number, utc: boolean): string {
  const p = fields(ms, utc);
  return `${pad(p.h)}:${pad(p.mi)}:${pad(p.s)}.${pad(new Date(ms).getUTCMilliseconds(), 3)}`;
}

/** "2026-11-28T09:05:01.123+01:00", or "…Z" in UTC. */
export function stamp(ms: number, utc: boolean): string {
  if (utc) return new Date(ms).toISOString();
  const p = fields(ms, false);
  const offset = -new Date(ms).getTimezoneOffset();
  const sign = offset < 0 ? "-" : "+";
  const zone = `${sign}${pad(Math.floor(Math.abs(offset) / 60))}:${pad(Math.abs(offset) % 60)}`;
  return `${p.y}-${pad(p.mo)}-${pad(p.d)}T${clock(ms, false)}${zone}`;
}

/** The text file of a pane: one line per row, a label in front of each line in a merged pane. */
export function downloadText(rows: Row[], options: { utc: boolean; labels: Map<string, string> | null }): string {
  const lines = rows.map((row) => {
    if (row.kind === "marker") return row.marker === "skipped" ? `# ${row.count} lines skipped` : "# Reconnected";
    const label = options.labels?.get(row.source);
    return `${stamp(row.ms, options.utc)} ${label ? `${label} ` : ""}${row.plain}${row.truncated ? "…" : ""}`;
  });
  return lines.map((line) => `${line}\n`).join("");
}

function slug(part: string): string {
  const trim = (s: string) => s.replace(/^-+|-+$/g, "");
  return trim(trim(part.toLowerCase().replace(/[^a-z0-9.]+/g, "-")).slice(0, MAX_SLUG));
}

/** "logs-<parts>-YYYYMMDD-HHMMSS.log" in local time. */
export function downloadName(parts: string[], at: Date): string {
  const date = `${at.getFullYear()}${pad(at.getMonth() + 1)}${pad(at.getDate())}`;
  const time = `${pad(at.getHours())}${pad(at.getMinutes())}${pad(at.getSeconds())}`;
  return `logs-${parts.map(slug).join("-")}-${date}-${time}.log`;
}
