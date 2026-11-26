import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { TopProcessesCard } from "@/components/servers/checks/top-processes-card";
import type { Proc, ServerCheck } from "@/lib/checks";

const now = new Date("2026-11-25T12:00:00Z");

const POSTGRES: Proc = { pid: 4242, name: "postgres", user: "postgres", cpu_percent: 87.5, memory_bytes: 536_870_912 };
const NGINX: Proc = { pid: 77, name: "nginx", user: "www-data", cpu_percent: 2, memory_bytes: 10_485_760 };

const CHECK: ServerCheck<"processes"> = {
  kind: "processes",
  status: "ok",
  checked_at: "2026-11-25T11:59:40Z",
  every_seconds: 30,
  data: { by_cpu: [POSTGRES, NGINX], by_memory: [POSTGRES] },
  data_at: "2026-11-25T11:59:40Z",
};

describe("TopProcessesCard", () => {
  it("lists the top processes by CPU and by memory", () => {
    render(<TopProcessesCard check={CHECK} now={now} canView groupName="Ops" />);
    expect(screen.getByRole("heading", { level: 3, name: "Top processes" })).toBeInTheDocument();
    const byCpu = screen.getByRole("list", { name: "By CPU" });
    const byMemory = screen.getByRole("list", { name: "By memory" });
    expect(within(byCpu).getAllByRole("listitem")).toHaveLength(2);
    expect(within(byMemory).getAllByRole("listitem")).toHaveLength(1);
    const row = within(byMemory).getByRole("listitem");
    expect(within(row).getByText("postgres", { selector: ".font-medium" })).toBeInTheDocument();
    expect(within(row).getByText("postgres", { selector: ".text-muted-foreground" })).toBeInTheDocument();
    expect(within(row).getByText("4242")).toHaveClass("font-mono");
    expect(within(row).getByText("87.5% CPU")).toBeInTheDocument();
    expect(within(row).getByText("512.0 MiB")).toBeInTheDocument();
    expect(within(byCpu).getByText("2.0% CPU")).toBeInTheDocument();
    expect(within(byCpu).getByText("10.0 MiB")).toBeInTheDocument();
    expect(screen.queryByText(/View processes right/)).not.toBeInTheDocument();
  });

  it("says the right is missing and shows no process, even when the check is ok", () => {
    render(<TopProcessesCard check={CHECK} now={now} canView={false} groupName="Ops" />);
    expect(screen.getByText("You need the View processes right in Ops to see processes.")).toBeInTheDocument();
    expect(screen.queryByText("postgres")).not.toBeInTheDocument();
    expect(screen.queryByText("nginx")).not.toBeInTheDocument();
    expect(screen.queryByRole("list")).not.toBeInTheDocument();
  });

  it("says the right is missing when the API sends no data", () => {
    render(<TopProcessesCard check={{ ...CHECK, data: null }} now={now} canView={false} groupName="Ops" />);
    expect(screen.getByText("You need the View processes right in Ops to see processes.")).toBeInTheDocument();
  });
});
