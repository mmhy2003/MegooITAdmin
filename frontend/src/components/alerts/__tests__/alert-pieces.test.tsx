import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AlertRows } from "@/components/alerts/alert-rows";
import { AlertStateBadge } from "@/components/alerts/alert-state-badge";
import { SeverityBadge } from "@/components/alerts/severity-badge";
import { formatTime } from "@/components/profile/profile-page";
import type { Alert } from "@/lib/alerts";

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

describe("SeverityBadge", () => {
  it("shows a warning as the word, in amber", () => {
    render(<SeverityBadge severity="warning" />);
    const badge = screen.getByText("Warning");
    expect(badge).toHaveAttribute("data-slot", "badge");
    expect(badge).toHaveAttribute("data-variant", "outline");
    expect(badge).toHaveClass("border-amber", "text-amber-ink");
  });

  it("shows a critical alert as the word, destructive", () => {
    render(<SeverityBadge severity="critical" />);
    expect(screen.getByText("Critical")).toHaveAttribute("data-variant", "destructive");
  });
});

describe("AlertStateBadge", () => {
  it.each([
    ["firing", "Firing"],
    ["resolved", "Resolved"],
    ["ended", "Ended"],
  ] as const)("shows %s as %j", (state, word) => {
    render(<AlertStateBadge state={state} />);
    expect(screen.getByText(word)).toHaveAttribute("data-slot", "badge");
  });

  it("shows a firing alert as destructive, a resolved one in green and an ended one muted", () => {
    render(
      <>
        <AlertStateBadge state="firing" />
        <AlertStateBadge state="resolved" />
        <AlertStateBadge state="ended" />
      </>,
    );
    expect(screen.getByText("Firing")).toHaveAttribute("data-variant", "destructive");
    expect(screen.getByText("Resolved")).toHaveClass("border-green", "text-green-ink");
    expect(screen.getByText("Ended")).toHaveClass("text-muted-foreground");
  });
});

describe("AlertRows", () => {
  const firing = alertOf();
  const resolved = alertOf({
    id: "a-2",
    server_id: "s-2",
    server_name: "db-01",
    metric: "mem.used_percent",
    instance: "",
    severity: "warning",
    state: "resolved",
    resolved_at: "2026-11-27T11:00:00Z",
    last_value: 80,
  });

  it("gives a table with the columns of an alert", () => {
    render(<AlertRows alerts={[firing]}>No alerts.</AlertRows>);
    const headers = screen.getAllByRole("columnheader").map((h) => h.textContent);
    expect(headers).toEqual(["Severity", "Server", "What happened", "Rule", "Fired", "Resolved", "State"]);
  });

  it("gives each alert its severity, server link, headline, rule, times and state", () => {
    render(<AlertRows alerts={[firing, resolved]}>No alerts.</AlertRows>);
    const [, first, second] = screen.getAllByRole("row");

    const one = within(first);
    expect(one.getByText("Critical")).toBeInTheDocument();
    expect(one.getByRole("link", { name: "web-01" })).toHaveAttribute("href", "/servers/s-1?tab=alerts");
    expect(one.getByText("web-01: / is 93.3% full")).toBeInTheDocument();
    expect(one.getByText("Space used above 90% for 10 min")).toBeInTheDocument();
    expect(one.getByText(formatTime("2026-11-27T10:00:00Z"))).toBeInTheDocument();
    expect(one.getByText("—")).toBeInTheDocument();
    expect(one.getByText("Firing")).toBeInTheDocument();

    const two = within(second);
    expect(two.getByText("Warning")).toBeInTheDocument();
    expect(two.getByRole("link", { name: "db-01" })).toHaveAttribute("href", "/servers/s-2?tab=alerts");
    expect(two.getByText("db-01: memory is 80.0% used")).toBeInTheDocument();
    expect(two.getByText("Memory used above 90% for 10 min")).toBeInTheDocument();
    expect(two.getByText(formatTime("2026-11-27T11:00:00Z"))).toBeInTheDocument();
    expect(two.getByText("Resolved")).toBeInTheDocument();
  });

  it("leaves out the Server column when showServer is false", () => {
    render(
      <AlertRows alerts={[firing]} showServer={false}>
        No alerts.
      </AlertRows>,
    );
    expect(screen.queryByRole("columnheader", { name: "Server" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.getAllByRole("cell")).toHaveLength(6);
  });

  it("shows its children instead of a table when there are no alerts", () => {
    render(<AlertRows alerts={[]}>No alerts are firing.</AlertRows>);
    expect(screen.getByText("No alerts are firing.")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("does not show its children when there are alerts", () => {
    render(<AlertRows alerts={[firing]}>No alerts are firing.</AlertRows>);
    expect(screen.queryByText("No alerts are firing.")).not.toBeInTheDocument();
  });
});
