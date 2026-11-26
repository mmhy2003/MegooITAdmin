import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ServicesCard } from "@/components/servers/checks/services-card";
import type { ServerCheck } from "@/lib/checks";

const now = new Date("2026-11-25T12:00:00Z");

const CHECK: ServerCheck<"services"> = {
  kind: "services",
  status: "ok",
  checked_at: "2026-11-25T11:59:30Z",
  every_seconds: 60,
  data: {
    total: 42,
    running: 40,
    failed: 1,
    failed_units: [{ unit: "nginx.service", description: "A high performance web server" }],
  },
  data_at: "2026-11-25T11:59:30Z",
};

describe("ServicesCard", () => {
  it("lists a failed unit with its description and a Failed badge", () => {
    render(<ServicesCard check={CHECK} now={now} />);
    expect(screen.getByRole("heading", { level: 3, name: "Services" })).toBeInTheDocument();
    expect(screen.getByText("40 running · 1 failed · 42 in all")).toBeInTheDocument();
    expect(screen.getByText("1 failed")).toHaveClass("text-pink-ink");
    const row = screen.getByRole("listitem");
    expect(within(row).getByText("nginx.service")).toHaveClass("font-mono");
    expect(within(row).getByText("A high performance web server")).toBeInTheDocument();
    expect(within(row).getByText("Failed")).toHaveClass("text-pink-ink");
  });

  it("says no service failed", () => {
    render(
      <ServicesCard
        check={{ ...CHECK, data: { total: 42, running: 42, failed: 0, failed_units: [] } }}
        now={now}
      />,
    );
    expect(screen.getByText("No failed services.")).toBeInTheDocument();
    expect(screen.getByText("All running")).toHaveClass("text-green-ink");
    expect(screen.queryByRole("listitem")).not.toBeInTheDocument();
  });
});
