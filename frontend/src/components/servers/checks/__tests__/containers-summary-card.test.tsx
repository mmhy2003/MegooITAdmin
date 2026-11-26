import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ContainersSummaryCard } from "@/components/servers/checks/containers-summary-card";
import type { ServerCheck } from "@/lib/checks";

const now = new Date("2026-11-25T12:00:00Z");

const CHECK: ServerCheck<"containers"> = {
  kind: "containers",
  status: "ok",
  checked_at: "2026-11-25T11:59:50Z",
  every_seconds: 30,
  data: { total: 4, running: 2, not_running: 2 },
  data_at: "2026-11-25T11:59:50Z",
};

describe("ContainersSummaryCard", () => {
  it("counts the running containers and links to the Containers tab", () => {
    render(<ContainersSummaryCard check={CHECK} now={now} href="/servers/s1?tab=containers" />);
    expect(screen.getByRole("heading", { level: 3, name: "Containers" })).toBeInTheDocument();
    expect(screen.getByText("2 running · 2 not running")).toBeInTheDocument();
    expect(screen.getByText("2 running")).toHaveClass("text-green-ink");
    expect(screen.getByRole("link", { name: "Show containers" })).toHaveAttribute(
      "href",
      "/servers/s1?tab=containers",
    );
  });

  it("says None when the server has no container", () => {
    render(
      <ContainersSummaryCard
        check={{ ...CHECK, data: { total: 0, running: 0, not_running: 0 } }}
        now={now}
        href="/servers/s1?tab=containers"
      />,
    );
    expect(screen.getByText("None")).toHaveClass("text-muted-foreground");
  });
});
