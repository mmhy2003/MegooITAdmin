// @vitest-environment node
import { describe, expect, it } from "vitest";
import {
  AMBER_FROM,
  fleetCounts,
  fleetOrder,
  formatBytes,
  formatLoad,
  formatPercent,
  formatRate,
  PINK_FROM,
  RANGE_LABELS,
  RANGES,
  rangeFrom,
  toneOf,
} from "@/lib/metrics";
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
