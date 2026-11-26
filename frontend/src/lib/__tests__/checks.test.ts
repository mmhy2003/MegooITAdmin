import { describe, expect, it } from "vitest";
import {
  agoText,
  certificateTone,
  checkOf,
  type CheckKind,
  type ChecksResponse,
  type Container,
  containerTone,
  everyText,
  groupContainers,
  isOld,
  NOT_AVAILABLE,
  type ServerCheck,
  STATE_TEXTS,
  TONE_CLASSES,
} from "@/lib/checks";

const NOW = new Date("2026-11-26T12:00:00Z");
const DAY = 86_400_000;

function ago(seconds: number): string {
  return new Date(NOW.getTime() - seconds * 1000).toISOString();
}

function container(name: string, project: string | null): Container {
  return {
    container_id: `id-${name}`,
    runtime: "docker",
    name,
    image: "nginx:1.27",
    compose_project: project,
    compose_service: project ? "web" : null,
    state: "running",
    status: "Up 2 hours",
    first_seen_at: "2026-11-26T10:00:00Z",
    last_seen_at: "2026-11-26T11:59:30Z",
  };
}

function check(checkedAt: string | null, every = 30): ServerCheck {
  return { kind: "services", status: "ok", checked_at: checkedAt, every_seconds: every, data: null, data_at: null };
}

describe("checkOf", () => {
  const response: ChecksResponse = {
    can_view_processes: true,
    checks: [
      { kind: "containers", status: "ok", checked_at: ago(10), every_seconds: 30, data: { total: 3, running: 2, not_running: 1 }, data_at: ago(10) },
      { kind: "updates", status: "timeout", checked_at: ago(60), every_seconds: 3600, data: null, data_at: null },
    ],
  };

  it("returns the check of the kind asked for", () => {
    const containers = checkOf(response, "containers");
    expect(containers.status).toBe("ok");
    expect(containers.data).toEqual({ total: 3, running: 2, not_running: 1 });
    expect(checkOf(response, "updates").status).toBe("timeout");
  });

  it("treats a kind the response does not carry as not checked", () => {
    expect(checkOf(response, "logins")).toEqual({
      kind: "logins",
      status: "not_checked",
      checked_at: null,
      every_seconds: 0,
      data: null,
      data_at: null,
    });
  });
});

describe("groupContainers", () => {
  it("orders projects by name with no project last, and containers by name inside", () => {
    const groups = groupContainers([
      container("shop-web-1", "shop"),
      container("hello-adhoc", null),
      container("monitoring-grafana-1", "monitoring"),
      container("shop-db-1", "shop"),
      container("another-adhoc", null),
    ]);
    expect(groups.map((group) => group.project)).toEqual(["monitoring", "shop", null]);
    expect(groups.map((group) => group.containers.map((item) => item.name))).toEqual([
      ["monitoring-grafana-1"],
      ["shop-db-1", "shop-web-1"],
      ["another-adhoc", "hello-adhoc"],
    ]);
  });

  it("returns no group for no containers", () => {
    expect(groupContainers([])).toEqual([]);
  });
});

describe("isOld", () => {
  it("is old only past three intervals", () => {
    expect(isOld(check(ago(90)), NOW)).toBe(false);
    expect(isOld(check(ago(91)), NOW)).toBe(true);
    expect(isOld(check(ago(10)), NOW)).toBe(false);
  });

  it("is not old when the check never ran", () => {
    expect(isOld(check(null), NOW)).toBe(false);
  });
});

describe("agoText", () => {
  it.each([
    [0, "just now"],
    [59, "just now"],
    [60, "1 minute ago"],
    [150, "2 minutes ago"],
    [3600, "1 hour ago"],
    [7200, "2 hours ago"],
    [86_400, "1 day ago"],
    [3 * 86_400, "3 days ago"],
  ])("%i seconds ago reads %s", (seconds, text) => {
    expect(agoText(ago(seconds), NOW)).toBe(text);
  });

  it("reads just now for a time slightly ahead of the clock", () => {
    expect(agoText(ago(-5), NOW)).toBe("just now");
  });
});

describe("everyText", () => {
  it.each([
    [30, "every 30 seconds"],
    [60, "every minute"],
    [300, "every 5 minutes"],
    [3600, "every hour"],
    [21600, "every 6 hours"],
    [1, "every second"],
    [90, "every 90 seconds"],
  ])("%i seconds reads %s", (seconds, text) => {
    expect(everyText(seconds)).toBe(text);
  });
});

describe("certificateTone", () => {
  const at = (days: number) => new Date(NOW.getTime() + days * DAY).toISOString();

  it.each([
    [-1, "pink", "Expired"],
    [3, "pink", "Expires in 3 days"],
    [10, "amber", "Expires in 10 days"],
    [40, "green", "Valid"],
  ])("%i days away is %s %s", (days, tone, label) => {
    expect(certificateTone(at(days), NOW)).toEqual({ tone, label });
  });

  it("says 1 day for the last day", () => {
    expect(certificateTone(at(0.5), NOW)).toEqual({ tone: "pink", label: "Expires in 1 day" });
  });
});

describe("containerTone", () => {
  it.each([
    ["running", "green"],
    ["paused", "amber"],
    ["restarting", "amber"],
    ["exited", "muted"],
    ["something-new", "muted"],
  ])("%s is %s", (state, tone) => {
    expect(containerTone(state)).toBe(tone);
  });
});

describe("texts", () => {
  it("gives every state but ok a badge and a text", () => {
    expect(STATE_TEXTS.not_checked).toEqual({
      badge: "Not checked yet",
      text: "The collector has not run this check yet.",
    });
    expect(STATE_TEXTS.denied.badge).toBe("Not allowed");
    expect(STATE_TEXTS.timeout).toEqual({ badge: "Could not be checked", text: "The check took too long." });
    expect(STATE_TEXTS.failed).toEqual({
      badge: "Could not be checked",
      text: "The check failed or printed something unexpected.",
    });
    expect(STATE_TEXTS.not_available.badge).toBe("Not available");
  });

  it("says why each check is not available", () => {
    const kinds: CheckKind[] = ["containers", "processes", "services", "logins", "updates", "certificates"];
    expect(Object.keys(NOT_AVAILABLE).sort()).toEqual([...kinds].sort());
    expect(NOT_AVAILABLE.containers).toBe("Docker is not installed on this server.");
  });

  it("gives each tone its classes", () => {
    expect(TONE_CLASSES).toEqual({
      pink: "border-pink text-pink-ink",
      amber: "border-amber text-amber-ink",
      green: "border-green text-green-ink",
      muted: "text-muted-foreground",
    });
  });
});
