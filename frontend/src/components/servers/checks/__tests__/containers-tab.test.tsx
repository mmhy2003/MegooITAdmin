import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ContainersTab } from "@/components/servers/checks/containers-tab";
import type { Container, ServerCheck } from "@/lib/checks";

const now = new Date("2026-11-25T12:00:00Z");

const CHECK: ServerCheck<"containers"> = {
  kind: "containers",
  status: "ok",
  checked_at: "2026-11-25T11:59:50Z",
  every_seconds: 30,
  data: { total: 4, running: 2, not_running: 2 },
  data_at: "2026-11-25T11:59:50Z",
};

function row(fields: Partial<Container> & Pick<Container, "container_id" | "name" | "image" | "state" | "status">) {
  return {
    runtime: "docker",
    compose_project: null,
    compose_service: null,
    first_seen_at: "2026-11-22T10:00:00Z",
    last_seen_at: "2026-11-25T11:59:50Z",
    ...fields,
  };
}

/** The four containers of the fake server, as the API returns them. */
const CONTAINERS: Container[] = [
  row({
    container_id: "1".repeat(64),
    name: "shop-web-1",
    image: "nginx:1.27",
    compose_project: "shop",
    compose_service: "web",
    state: "running",
    status: "Up 3 days (healthy)",
  }),
  row({
    container_id: "2".repeat(64),
    name: "shop-db-1",
    image: "postgres:17",
    compose_project: "shop",
    compose_service: "db",
    state: "running",
    status: "Up 3 days",
  }),
  row({
    container_id: "3".repeat(64),
    name: "monitoring-grafana-1",
    image: "grafana/grafana:11.3.0",
    compose_project: "monitoring",
    compose_service: "grafana",
    state: "exited",
    status: "Exited (0) 2 hours ago",
  }),
  row({
    container_id: "4".repeat(64),
    name: "hello-adhoc",
    image: "busybox:1.37",
    state: "restarting",
    status: "Restarting (1) 5 seconds ago",
  }),
];

function sectionHeadings(): string[] {
  return screen
    .getAllByRole("heading", { level: 3 })
    .map((heading) => heading.textContent ?? "")
    .filter((text) => text !== "Containers");
}

function rowOf(name: string): HTMLElement {
  const cell = screen.getByText(name);
  return cell.closest("tr") as HTMLElement;
}

describe("ContainersTab", () => {
  it("groups the containers by Compose project, with no project last", () => {
    render(<ContainersTab check={CHECK} containers={CONTAINERS} now={now} />);
    expect(screen.getByRole("heading", { level: 3, name: "Containers" })).toBeInTheDocument();
    expect(sectionHeadings()).toEqual(["monitoring", "shop", "No Compose project"]);
    const shop = screen.getAllByRole("table")[1];
    const names = within(shop)
      .getAllByRole("row")
      .slice(1)
      .map((tr) => within(tr).getAllByRole("cell")[0].textContent);
    expect(names).toEqual(["shop-db-1", "shop-web-1"]);
  });

  it("shows each container's columns and a state badge in its tone", () => {
    render(<ContainersTab check={CHECK} containers={CONTAINERS} now={now} />);
    for (const name of ["Name", "Service", "Image", "State", "Status", "Last seen"]) {
      expect(screen.getAllByRole("columnheader", { name }).length).toBe(3);
    }
    const web = rowOf("shop-web-1");
    expect(within(web).getByText("shop-web-1")).toHaveClass("font-mono");
    expect(within(web).getByText("web")).toBeInTheDocument();
    expect(within(web).getByText("nginx:1.27")).toHaveClass("font-mono");
    expect(within(web).getByText("running")).toHaveClass("text-green-ink");
    expect(within(web).getByText("Up 3 days (healthy)")).toBeInTheDocument();
    expect(within(rowOf("hello-adhoc")).getByText("restarting")).toHaveClass("text-amber-ink");
    expect(within(rowOf("monitoring-grafana-1")).getByText("exited")).toHaveClass("text-muted-foreground");
  });

  it("asks to run the setup script again when sudo refused, without a table", () => {
    render(<ContainersTab check={{ ...CHECK, status: "denied", data: null, data_at: null }} containers={[]} now={now} />);
    expect(screen.getByText(/Run megoo-setup\.sh on it again/)).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("says Docker is not installed", () => {
    render(
      <ContainersTab check={{ ...CHECK, status: "not_available", data: null, data_at: null }} containers={[]} now={now} />,
    );
    expect(screen.getByText("Docker is not installed on this server.")).toBeInTheDocument();
  });

  it("says the server has no containers", () => {
    render(
      <ContainersTab check={{ ...CHECK, data: { total: 0, running: 0, not_running: 0 } }} containers={[]} now={now} />,
    );
    expect(screen.getByText("No containers on this server.")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("keeps the last listing and says it is old when the check stopped running", () => {
    render(
      <ContainersTab
        check={{ ...CHECK, status: "timeout", checked_at: "2026-11-25T11:00:00Z" }}
        containers={CONTAINERS}
        now={now}
      />,
    );
    expect(screen.getByTestId("check-footer")).toHaveTextContent("Last checked 1 hour ago · every 30 seconds");
    expect(screen.getByText("shop-web-1")).toBeInTheDocument();
  });
});
