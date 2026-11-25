import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MonitoringBadge } from "@/components/servers/monitoring-badge";

const since = "2026-11-25T10:00:00Z";
const last_sample_at = "2026-11-25T10:05:00Z";

describe("MonitoringBadge", () => {
  it("shows a reachable server in green, with a dot hidden from assistive technology", () => {
    render(<MonitoringBadge monitoring={{ state: "reachable", reason: null, since, last_sample_at }} />);
    const badge = screen.getByText("Reachable");
    expect(badge).toHaveAttribute("data-slot", "badge");
    expect(badge).toHaveClass("border-green");
    expect(badge.querySelector("span")).toHaveAttribute("aria-hidden", "true");
  });

  it("shows an unreachable server as destructive", () => {
    render(<MonitoringBadge monitoring={{ state: "unreachable", reason: "no_samples", since, last_sample_at }} />);
    expect(screen.getByText("Unreachable")).toHaveAttribute("data-variant", "destructive");
  });

  it("shows a server that is not monitored as an outline", () => {
    render(
      <MonitoringBadge monitoring={{ state: "not_monitored", reason: "not_an_ssh_server", since, last_sample_at: null }} />,
    );
    expect(screen.getByText("Not monitored")).toHaveAttribute("data-variant", "outline");
  });

  it("shows a server the collector has not checked yet with a dashed border", () => {
    render(<MonitoringBadge monitoring={null} />);
    expect(screen.getByText("Not checked yet")).toHaveClass("border-dashed");
  });
});
