// @vitest-environment node
import { describe, expect, it } from "vitest";
import {
  AMBER_FROM,
  appendSample,
  applyMessage,
  chartRows,
  emptyTrend,
  fleetCounts,
  fleetOrder,
  formatBytes,
  formatLoad,
  formatPercent,
  formatRate,
  instancesOf,
  isStale,
  lastValue,
  mergeOverview,
  PINK_FROM,
  pushTrend,
  RANGE_LABELS,
  RANGES,
  rangeFrom,
  seriesOf,
  sumSeries,
  toneOf,
  TREND_SLOTS,
  TREND_STEP_MS,
  trendOf,
  vitalsOf,
} from "@/lib/metrics";
import type { ChartLine, Overview, OverviewMessage, SampleMessage, Series, SeriesAnswer, Trend } from "@/lib/metrics";
import type { Monitoring, MonitoringState, Server } from "@/lib/servers";

function monitoring(state: MonitoringState): Monitoring {
  return { state, reason: null, since: "2026-11-26T12:00:00Z", last_sample_at: null };
}

function server(name: string, state: MonitoringState | null): Server {
  return {
    id: `id-${name}`,
    name,
    address: "10.0.0.1",
    port: 22,
    os: "linux",
    role: null,
    tags: [],
    group_id: "g",
    group_name: "Group",
    connection_settings: { username: "megoo" },
    host_key: null,
    created_at: "2026-11-26T12:00:00Z",
    updated_at: "2026-11-26T12:00:00Z",
    can_manage: false,
    host_key_state: "pinned",
    host_key_fingerprint: null,
    host_key_type: null,
    host_key_pinned_at: null,
    host_key_changed_at: null,
    host_key_offered: null,
    can_connect: true,
    metrics_interval_seconds: 5,
    monitoring: state === null ? null : monitoring(state),
  };
}

describe("toneOf", () => {
  it("turns amber from 80% and pink from 90%", () => {
    expect(AMBER_FROM).toBe(80);
    expect(PINK_FROM).toBe(90);
    expect(toneOf(79)).toBe("normal");
    expect(toneOf(79.9)).toBe("normal");
    expect(toneOf(80)).toBe("amber");
    expect(toneOf(89)).toBe("amber");
    expect(toneOf(89.9)).toBe("amber");
    expect(toneOf(90)).toBe("pink");
    expect(toneOf(100)).toBe("pink");
  });

  it("keeps an unknown value normal", () => {
    expect(toneOf(null)).toBe("normal");
  });
});

describe("formatPercent", () => {
  it("rounds to a whole percent", () => {
    expect(formatPercent(42.4)).toBe("42%");
    expect(formatPercent(0)).toBe("0%");
  });

  it("shows a dash for an unknown value", () => {
    expect(formatPercent(null)).toBe("—");
  });
});

describe("formatBytes", () => {
  it("uses binary units with one decimal under 10 and none from 10", () => {
    expect(formatBytes(0)).toBe("0 B");
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(1536)).toBe("1.5 KiB");
    expect(formatBytes(16 * 2 ** 30)).toBe("16 GiB");
    expect(formatBytes(10.4 * 2 ** 20)).toBe("10 MiB");
  });

  it("does not show 10.0 when a value rounds up to ten", () => {
    expect(formatBytes(9.97 * 1024)).toBe("10 KiB");
  });

  it("shows a dash for an unknown value", () => {
    expect(formatBytes(null)).toBe("—");
  });
});

describe("formatRate", () => {
  it("adds per second to the bytes", () => {
    expect(formatRate(2048)).toBe("2.0 KiB/s");
    expect(formatRate(0)).toBe("0 B/s");
  });

  it("shows a dash for an unknown value", () => {
    expect(formatRate(null)).toBe("—");
  });
});

describe("formatLoad", () => {
  it("shows two decimals", () => {
    expect(formatLoad(0.5)).toBe("0.50");
    expect(formatLoad(12.345)).toBe("12.35");
  });

  it("shows a dash for an unknown value", () => {
    expect(formatLoad(null)).toBe("—");
  });
});

describe("ranges", () => {
  it("lists the seven ranges with their labels", () => {
    expect(RANGES).toEqual(["live", "1h", "6h", "24h", "7d", "30d", "1y"]);
    expect(RANGE_LABELS["7d"]).toBe("7 days");
    expect(RANGE_LABELS.live).toBe("Live");
  });

  it("reads the range from the address", () => {
    expect(rangeFrom(new URLSearchParams("range=7d"))).toBe("7d");
    expect(rangeFrom(new URLSearchParams("range=1y"))).toBe("1y");
  });

  it("falls back to live for an unknown or missing range", () => {
    expect(rangeFrom(new URLSearchParams("range=90d"))).toBe("live");
    expect(rangeFrom(new URLSearchParams(""))).toBe("live");
  });
});

describe("fleetOrder", () => {
  it("puts unreachable first, then reachable, then the rest, each by name", () => {
    const servers = [
      server("b-unreach", "unreachable"),
      server("a-reach", "reachable"),
      server("c-null", null),
      server("d-notmon", "not_monitored"),
      server("a-unreach", "unreachable"),
    ];
    expect(fleetOrder(servers).map((s) => s.name)).toEqual([
      "a-unreach",
      "b-unreach",
      "a-reach",
      "c-null",
      "d-notmon",
    ]);
  });

  it("sorts not monitored and not checked together by name", () => {
    const servers = [server("z-null", null), server("m-notmon", "not_monitored")];
    expect(fleetOrder(servers).map((s) => s.name)).toEqual(["m-notmon", "z-null"]);
  });

  it("leaves the given list untouched", () => {
    const servers = [server("b", "reachable"), server("a", "unreachable")];
    fleetOrder(servers);
    expect(servers.map((s) => s.name)).toEqual(["b", "a"]);
  });
});

describe("fleetCounts", () => {
  it("counts every monitoring state", () => {
    const servers = [
      server("a", "reachable"),
      server("b", "reachable"),
      server("c", "unreachable"),
      server("d", "not_monitored"),
      server("e", null),
      server("f", null),
    ];
    expect(fleetCounts(servers)).toEqual({
      total: 6,
      reachable: 2,
      unreachable: 1,
      notMonitored: 1,
      notChecked: 2,
    });
  });

  it("counts an empty fleet as zero", () => {
    expect(fleetCounts([])).toEqual({ total: 0, reachable: 0, unreachable: 0, notMonitored: 0, notChecked: 0 });
  });
});

const START = "2026-11-26T10:00:00Z";
const START_MS = Date.parse(START);

function slots(fill: (i: number) => number | null = () => null): (number | null)[] {
  return Array.from({ length: TREND_SLOTS }, (_, i) => fill(i));
}

function overview(fields: Partial<Overview> = {}): Overview {
  return { server_id: "s1", time: START, cpu: 10, mem: 20, load: 0.5, disk: { mount: "/", percent: 30 }, rx: 100, tx: 200, ...fields };
}

function series(metric: string, instance: string, points: [string, number][]): Series {
  return {
    metric,
    instance,
    time: points.map(([t]) => t),
    avg: points.map(([, v]) => v),
    min: points.map(() => null),
    max: points.map(() => null),
  };
}

function at(seconds: number): string {
  return new Date(START_MS + seconds * 1000).toISOString();
}

describe("trendOf", () => {
  it("reads the start in milliseconds and copies the arrays", () => {
    const read = { start: START, cpu: slots((i) => i), mem: slots() };
    const trend = trendOf(read);
    expect(trend.start).toBe(START_MS);
    expect(trend.cpu).toEqual(read.cpu);
    expect(trend.cpu).not.toBe(read.cpu);
    expect(trend.mem).not.toBe(read.mem);
  });
});

describe("emptyTrend", () => {
  it("has sixty empty slots and puts the end time in the last one", () => {
    const end = START_MS + 59 * TREND_STEP_MS + 2_000;
    const trend = emptyTrend(end);
    expect(trend.start).toBe(START_MS);
    expect(trend.cpu).toEqual(slots());
    expect(trend.mem).toEqual(slots());
  });
});

describe("pushTrend", () => {
  const LAST = START_MS + 59 * TREND_STEP_MS;
  const trend = (): Trend => ({ start: START_MS, cpu: slots((i) => i), mem: slots((i) => 100 + i) });

  it("sets the last slot for a time inside it", () => {
    const next = pushTrend(trend(), LAST + 1_000, 7, 8);
    expect(next.start).toBe(START_MS);
    expect(next.cpu[59]).toBe(7);
    expect(next.mem[59]).toBe(8);
    expect(next.cpu[58]).toBe(58);
  });

  it("shifts the window so the new time is in the last slot", () => {
    const next = pushTrend(trend(), LAST + 2 * TREND_STEP_MS, 7, 8);
    expect(next.start).toBe(START_MS + 2 * TREND_STEP_MS);
    expect(next.cpu).toHaveLength(TREND_SLOTS);
    expect(next.mem).toHaveLength(TREND_SLOTS);
    expect(next.cpu[57]).toBe(59);
    expect(next.cpu[58]).toBeNull();
    expect(next.cpu[59]).toBe(7);
    expect(next.mem[57]).toBe(159);
    expect(next.mem[59]).toBe(8);
  });

  it("empties every slot but the last after sixty or more slots", () => {
    const next = pushTrend(trend(), LAST + 61 * TREND_STEP_MS, 7, 8);
    expect(next.cpu).toEqual(slots((i) => (i === 59 ? 7 : null)));
    expect(next.mem).toEqual(slots((i) => (i === 59 ? 8 : null)));
  });

  it("ignores a time older than the window", () => {
    const before = trend();
    expect(pushTrend(before, START_MS - 1, 7, 8)).toEqual(before);
  });

  it("keeps the slot's value for a null", () => {
    const next = pushTrend(trend(), LAST, null, 8);
    expect(next.cpu[59]).toBe(59);
    expect(next.mem[59]).toBe(8);
  });

  it("leaves the given trend untouched", () => {
    const before = trend();
    pushTrend(before, LAST + 2 * TREND_STEP_MS, 7, 8);
    expect(before).toEqual(trend());
  });
});

describe("vitalsOf", () => {
  it("splits a read into its overview and trend", () => {
    const read = { ...overview(), trend: { start: START, cpu: slots(), mem: slots() } };
    const vitals = vitalsOf(read);
    expect(vitals.overview).toEqual(overview());
    expect(vitals.overview).not.toHaveProperty("trend");
    expect(vitals.trend.start).toBe(START_MS);
  });
});

describe("mergeOverview", () => {
  it("keeps the previous value of each field the next one lacks", () => {
    const merged = mergeOverview(overview(), overview({ time: at(5), cpu: 50, rx: null, tx: null }));
    expect(merged).toEqual(overview({ time: at(5), cpu: 50 }));
  });

  it("keeps the previous time when the next has none", () => {
    expect(mergeOverview(overview(), overview({ time: null })).time).toBe(START);
  });

  it("takes the next one when there is no previous", () => {
    const next = overview({ rx: null });
    expect(mergeOverview(null, next)).toEqual(next);
  });
});

describe("applyMessage", () => {
  const message = (fields: Partial<OverviewMessage> = {}): OverviewMessage => ({
    ...overview(),
    type: "overview",
    time: at(59 * 5 + 1),
    ...fields,
  });

  it("starts an empty trend ending at the message's time", () => {
    const vitals = applyMessage(undefined, message());
    expect(vitals.trend.start).toBe(START_MS);
    expect(vitals.trend.cpu).toEqual(slots((i) => (i === 59 ? 10 : null)));
    expect(vitals.trend.mem[59]).toBe(20);
    expect(vitals.overview).toEqual(overview({ time: at(59 * 5 + 1) }));
    expect(vitals.overview).not.toHaveProperty("type");
  });

  it("merges into the previous vitals and pushes onto their trend", () => {
    const first = applyMessage(undefined, message());
    const second = applyMessage(first, message({ time: at(60 * 5), cpu: 70, rx: null }));
    expect(second.overview.rx).toBe(100);
    expect(second.overview.cpu).toBe(70);
    expect(second.trend.cpu[58]).toBe(10);
    expect(second.trend.cpu[59]).toBe(70);
  });
});

describe("isStale", () => {
  const now = START_MS;

  it("counts a missing time as stale", () => {
    expect(isStale(null, now)).toBe(true);
  });

  it("is stale only after five minutes", () => {
    expect(isStale(new Date(now - 4 * 60_000).toISOString(), now)).toBe(false);
    expect(isStale(new Date(now - 6 * 60_000).toISOString(), now)).toBe(true);
  });
});

describe("appendSample", () => {
  const sample = (time: string, readings: SampleMessage["readings"]): SampleMessage => ({
    type: "sample",
    server_id: "s1",
    time,
    readings,
  });

  it("appends to a known series and starts one for a new instance after it", () => {
    const live = [series("cpu.used_percent", "", [[at(0), 10]])];
    const next = appendSample(
      live,
      sample(at(5), [
        ["cpu.used_percent", "", 20],
        ["cpu.used_percent", "cpu0", 30],
        ["mem.used_percent", "", 40],
      ]),
      ["cpu.used_percent"],
      60_000,
    );
    expect(next).toEqual([
      series("cpu.used_percent", "", [
        [at(0), 10],
        [at(5), 20],
      ]),
      series("cpu.used_percent", "cpu0", [[at(5), 30]]),
    ]);
    expect(live[0].avg).toEqual([10]);
  });

  it("drops points older than the window", () => {
    const live = [
      series("cpu.used_percent", "", [
        [at(0), 1],
        [at(10), 2],
      ]),
    ];
    const next = appendSample(live, sample(at(70), [["cpu.used_percent", "", 3]]), ["cpu.used_percent"], 60_000);
    expect(next[0]).toEqual(
      series("cpu.used_percent", "", [
        [at(10), 2],
        [at(70), 3],
      ]),
    );
  });
});

describe("sumSeries", () => {
  it("adds every series at each time present in any of them", () => {
    const eth0 = series("net.rx_bytes", "eth0", [
      [at(0), 100],
      [at(5), 200],
    ]);
    const eth1 = series("net.rx_bytes", "eth1", [
      [at(5), 50],
      [at(10), 5],
    ]);
    expect(sumSeries([eth1, eth0], "net.rx_bytes", "")).toEqual(
      series("net.rx_bytes", "", [
        [at(0), 100],
        [at(5), 250],
        [at(10), 5],
      ]),
    );
  });
});

describe("chartRows", () => {
  const line = (key: string, s: Series, band = false): ChartLine => ({ key, label: key, color: "var(--chart-1)", series: s, band });

  it("joins the lines by time and breaks where points are more than three steps apart", () => {
    const a = series("cpu.used_percent", "", [
      [at(10), 1],
      [at(0), 0],
      [at(50), 3],
    ]);
    const b = series("mem.used_percent", "", [[at(10), 2]]);
    const rows = chartRows([line("a", a), line("b", b)], 10_000);
    expect(rows).toEqual([
      { t: START_MS, a: 0, b: null },
      { t: START_MS + 10_000, a: 1, b: 2 },
      { t: START_MS + 30_000, a: null, b: null },
      { t: START_MS + 50_000, a: 3, b: null },
    ]);
  });

  it("does not break at exactly three steps", () => {
    const a = series("cpu.used_percent", "", [
      [at(0), 0],
      [at(30), 1],
    ]);
    expect(chartRows([line("a", a)], 10_000)).toHaveLength(2);
  });

  it("adds a band only when asked and both ends are known", () => {
    const a: Series = { ...series("cpu.used_percent", "", [[at(0), 5], [at(10), 6]]), min: [1, null], max: [9, 8] };
    expect(chartRows([line("a", a, true)], 10_000)).toEqual([
      { t: START_MS, a: 5, a_band: [1, 9] },
      { t: START_MS + 10_000, a: 6, a_band: null },
    ]);
    expect(chartRows([line("a", a)], 10_000)[0]).not.toHaveProperty("a_band");
  });
});

describe("answer helpers", () => {
  const answer: SeriesAnswer = {
    range: "1h",
    step_seconds: 60,
    start: START,
    end: at(3600),
    series: [
      series("disk.used_percent", "/var", [[at(0), 1]]),
      series("disk.used_percent", "", [[at(0), 2]]),
      series("disk.used_percent", "/", [[at(0), 3]]),
      series("cpu.used_percent", "", [[at(0), 4]]),
    ],
  };

  it("finds a series by metric and instance", () => {
    expect(seriesOf(answer, "cpu.used_percent")?.avg).toEqual([4]);
    expect(seriesOf(answer, "disk.used_percent", "/")?.avg).toEqual([3]);
    expect(seriesOf(answer, "load.1")).toBeUndefined();
    expect(seriesOf(null, "cpu.used_percent")).toBeUndefined();
  });

  it("lists the instances of a metric sorted, without the empty one", () => {
    expect(instancesOf(answer, "disk.used_percent")).toEqual(["/", "/var"]);
    expect(instancesOf(null, "disk.used_percent")).toEqual([]);
  });

  it("gives the last value of a series", () => {
    expect(lastValue(series("cpu.used_percent", "", []))).toBeNull();
    expect(lastValue(undefined)).toBeNull();
    expect(lastValue(series("cpu.used_percent", "", [[at(0), 1], [at(5), 2]]))).toBe(2);
  });
});
