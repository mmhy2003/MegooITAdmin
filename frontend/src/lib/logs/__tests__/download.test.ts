import { describe, expect, it } from "vitest";
import { clock, downloadName, downloadText, stamp } from "@/lib/logs/download";
import type { LineRow, MarkerRow } from "@/lib/logs/store";

const MS = Date.UTC(2026, 10, 28, 9, 5, 1, 123);

function line(source: string, seq: number, plain: string, truncated = false): LineRow {
  return {
    kind: "line",
    key: `${source}:0:${seq}`,
    source,
    run: 0,
    seq,
    time: new Date(MS).toISOString(),
    ms: MS,
    text: `\u001b[31m${plain}\u001b[0m`,
    plain,
    level: "info",
    unit: null,
    truncated,
  };
}

function marker(source: string, kind: "skipped" | "reconnected", count = 0): MarkerRow {
  return { kind: "marker", key: `${source}:m1`, source, ms: MS, marker: kind, count };
}

describe("stamp", () => {
  it("gives the exact time in UTC", () => {
    expect(stamp(MS, true)).toBe("2026-11-28T09:05:01.123Z");
  });

  it("gives the local time with its offset", () => {
    const local = stamp(MS, false);
    expect(local).toMatch(/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.123[+-]\d\d:\d\d$/);
    expect(Date.parse(local)).toBe(MS);
  });
});

describe("clock", () => {
  it("gives hours, minutes, seconds and milliseconds", () => {
    expect(clock(MS, true)).toBe("09:05:01.123");
    expect(clock(MS, false)).toMatch(/^\d\d:\d\d:01\.123$/);
  });
});

describe("downloadText", () => {
  const rows = [
    line("a", 1, "started"),
    line("b", 2, "very long", true),
    marker("a", "skipped", 12),
    marker("b", "reconnected"),
  ];

  it("writes each line with its time and plain text", () => {
    expect(downloadText(rows, { utc: true, labels: null })).toBe(
      "2026-11-28T09:05:01.123Z started\n" +
        "2026-11-28T09:05:01.123Z very long…\n" +
        "# 12 lines skipped\n" +
        "# Reconnected\n",
    );
  });

  it("puts the label of the source in front when labels are given", () => {
    const labels = new Map([
      ["a", "web-1 Journal"],
      ["b", "db-1 Container · pg"],
    ]);
    expect(downloadText(rows.slice(0, 2), { utc: true, labels })).toBe(
      "2026-11-28T09:05:01.123Z web-1 Journal started\n" + "2026-11-28T09:05:01.123Z db-1 Container · pg very long…\n",
    );
  });
});

describe("downloadName", () => {
  const at = new Date(2026, 10, 28, 9, 5, 1);

  it("joins the slugs and the local date and time", () => {
    expect(downloadName(["Web-1", "Journal · nginx.service"], at)).toBe(
      "logs-web-1-journal-nginx.service-20261128-090501.log",
    );
    expect(downloadName(["merged"], at)).toBe("logs-merged-20261128-090501.log");
  });

  it("trims the slugs and keeps at most 40 characters", () => {
    expect(downloadName(["  /var/log/syslog  "], at)).toBe("logs-var-log-syslog-20261128-090501.log");
    expect(downloadName(["x".repeat(50)], at)).toBe(`logs-${"x".repeat(40)}-20261128-090501.log`);
    expect(downloadName([`${"y".repeat(39)} z`], at)).toBe(`logs-${"y".repeat(39)}-20261128-090501.log`);
  });
});
