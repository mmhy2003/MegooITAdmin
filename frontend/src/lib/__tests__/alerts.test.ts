import { describe, expect, it } from "vitest";
import {
  type Alert,
  type AlertEvent,
  type AlertMetric,
  alertHeadline,
  alertsPath,
  durationText,
  END_REASON_TEXT,
  eventSentence,
  firingByServer,
  METRICS,
  ruleSentence,
  SEVERITY_LABEL,
  valueText,
} from "@/lib/alerts";

function alertOf(fields: Partial<Alert> = {}): Alert {
  return {
    id: "a-1",
    server_id: "s-1",
    server_name: "web-01",
    group_id: "g-1",
    group_name: "staging",
    rule_id: "r-1",
    rule_name: "Filesystem almost full",
    metric: "disk.used_percent",
    comparison: "above",
    threshold: 90,
    duration_seconds: 600,
    severity: "critical",
    instance: "/",
    state: "firing",
    end_reason: null,
    fired_at: "2026-11-27T10:00:00Z",
    resolved_at: null,
    value: 93.25,
    last_value: 91,
    peak_value: 95,
    ...fields,
  };
}

function eventOf(kind: AlertEvent["kind"], fields: Partial<Alert> = {}): AlertEvent {
  return { id: "e-1", kind, at: "2026-11-27T10:00:00Z", alert: alertOf(fields) };
}

describe("durationText", () => {
  it.each([
    [0, ""],
    [30, "1 min"],
    [600, "10 min"],
    [3600, "1 h"],
    [5400, "1 h 30 min"],
    [7200, "2 h"],
  ])("%i s → %j", (seconds, text) => {
    expect(durationText(seconds)).toBe(text);
  });
});

describe("ruleSentence", () => {
  it.each<[AlertMetric, string]>([
    ["cpu.used_percent", "CPU used above 90% for 10 min"],
    ["mem.used_percent", "Memory used above 90% for 10 min"],
    ["disk.used_percent", "Space used above 90% for 10 min"],
    ["disk.inodes_used_percent", "Inodes used above 90% for 10 min"],
    ["load.1m", "Load per core (1 min) above 90 per core for 10 min"],
    ["load.5m", "Load per core (5 min) above 90 per core for 10 min"],
    ["load.15m", "Load per core (15 min) above 90 per core for 10 min"],
  ])("%s → %s", (metric, text) => {
    expect(ruleSentence({ metric, comparison: "above", threshold: 90, duration_seconds: 600 })).toBe(text);
  });

  it("says unreachable for the duration", () => {
    expect(ruleSentence({ metric: "unreachable", comparison: null, threshold: null, duration_seconds: 300 })).toBe(
      "Unreachable for 5 min",
    );
  });

  it("leaves out the duration when it is 0", () => {
    expect(ruleSentence({ metric: "mem.used_percent", comparison: "below", threshold: 2.5, duration_seconds: 0 })).toBe(
      "Memory used below 2.5%",
    );
    expect(ruleSentence({ metric: "unreachable", comparison: null, threshold: null, duration_seconds: 0 })).toBe(
      "Unreachable",
    );
  });
});

describe("valueText", () => {
  it("gives percentages with one decimal", () => {
    expect(valueText("disk.used_percent", 93.25)).toBe("93.3%");
    expect(valueText("cpu.used_percent", 90)).toBe("90.0%");
  });

  it("gives load with two decimals per core", () => {
    expect(valueText("load.5m", 1.5)).toBe("1.50 per core");
  });
});

describe("alertHeadline", () => {
  it.each<[Partial<Alert>, string]>([
    [{ metric: "cpu.used_percent", instance: "" }, "web-01: CPU is 93.3% busy"],
    [{ metric: "mem.used_percent", instance: "" }, "web-01: memory is 93.3% used"],
    [{ metric: "disk.used_percent", instance: "/var" }, "web-01: /var is 93.3% full"],
    [{ metric: "disk.inodes_used_percent", instance: "/var" }, "web-01: /var has 93.3% of its inodes used"],
    [{ metric: "load.1m", instance: "", value: 2 }, "web-01: load is 2.00 per core (1 min)"],
    [{ metric: "load.5m", instance: "", value: 2 }, "web-01: load is 2.00 per core (5 min)"],
    [{ metric: "load.15m", instance: "", value: 2 }, "web-01: load is 2.00 per core (15 min)"],
    [{ metric: "unreachable", comparison: null, threshold: null, instance: "", value: null }, "web-01 is unreachable"],
  ])("%j → %s", (fields, text) => {
    expect(alertHeadline(alertOf(fields))).toBe(text);
  });

  it("tells a resolved alert with its last value", () => {
    expect(alertHeadline(alertOf({ state: "resolved", resolved_at: "2026-11-27T10:20:00Z" }))).toBe(
      "web-01: / is 91.0% full",
    );
  });
});

describe("eventSentence", () => {
  it("tells a fired event with its headline", () => {
    expect(eventSentence(eventOf("fired"))).toBe("web-01: / is 93.3% full");
  });

  it("tells a fired event with the fired value once its alert has resolved", () => {
    expect(eventSentence(eventOf("fired", { state: "resolved" }))).toBe("web-01: / is 93.3% full");
  });

  it("tells a resolved event with the last value", () => {
    expect(eventSentence(eventOf("resolved", { state: "resolved" }))).toBe("Resolved: web-01: / is 91.0% full");
  });

  it("tells a resolved unreachable alert that the server is reachable again", () => {
    const event = eventOf("resolved", { metric: "unreachable", comparison: null, threshold: null, value: null });
    expect(eventSentence(event)).toBe("Resolved: web-01 is reachable again");
  });

  it.each([
    ["rule_changed", "the rule was changed"],
    ["rule_disabled", "the rule was switched off"],
    ["rule_deleted", "the rule was deleted"],
    ["server_not_monitored", "the server is no longer monitored"],
  ] as const)("tells an ended event with %s", (reason, text) => {
    const event = eventOf("ended", { state: "ended", end_reason: reason });
    expect(eventSentence(event)).toBe(`Ended: web-01: Filesystem almost full, ${text}`);
    expect(END_REASON_TEXT[reason]).toBe(text);
  });
});

describe("SEVERITY_LABEL and METRICS", () => {
  it("names each severity", () => {
    expect(SEVERITY_LABEL).toEqual({ warning: "Warning", critical: "Critical" });
  });

  it("describes each metric as the backend's catalog does", () => {
    expect(METRICS["disk.used_percent"]).toEqual({ label: "Space used", unit: "%", max: 100, perInstance: true });
    expect(METRICS["load.15m"]).toEqual({ label: "Load per core (15 min)", unit: "per core", max: 1000, perInstance: false });
    expect(METRICS.unreachable).toEqual({ label: "Unreachable", unit: null, max: null, perInstance: false });
    expect(Object.keys(METRICS)).toHaveLength(8);
  });
});

describe("alertsPath", () => {
  it("reads the firing alerts of every server", () => {
    expect(alertsPath("firing", { group: null, tags: [] })).toBe("/alerts?state=firing");
  });

  it("reads closed alerts of a group with tags, after the last one shown", () => {
    const last = { id: "a-9", resolved_at: "2026-11-27T10:00:00Z" };
    expect(alertsPath("closed", { group: "g-1", tags: ["eu", "web"] }, last)).toBe(
      "/alerts?group_id=g-1&tag=eu&tag=web&state=closed&before=2026-11-27T10%3A00%3A00Z&before_id=a-9",
    );
  });
});

describe("firingByServer", () => {
  it("counts the firing alerts of each server", () => {
    const alerts = [
      alertOf({ id: "a-1", server_id: "s-1" }),
      alertOf({ id: "a-2", server_id: "s-2" }),
      alertOf({ id: "a-3", server_id: "s-1" }),
      alertOf({ id: "a-4", server_id: "s-3", state: "resolved" }),
    ];
    expect(firingByServer(alerts)).toEqual({ "s-1": 2, "s-2": 1 });
  });

  it("is empty without alerts", () => {
    expect(firingByServer([])).toEqual({});
  });
});
