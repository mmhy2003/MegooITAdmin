import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { FleetSummary } from "@/components/dashboard/fleet-summary";
import { ServerCard } from "@/components/dashboard/server-card";
import { ServerRows } from "@/components/dashboard/server-rows";
import { ViewSwitch } from "@/components/dashboard/view-switch";
import { NOW, server, vitals } from "./fixtures";

describe("FleetSummary", () => {
  it("counts ten servers of mixed states, each number with its label", () => {
    const servers = [
      ...["a", "b", "c", "d", "e"].map((n) => server(n, "reachable")),
      server("f", "unreachable"),
      server("g", "unreachable"),
      server("h", "not_monitored"),
      server("i", null),
      server("j", null),
    ];
    render(<FleetSummary servers={servers} />);
    const tile = (label: string) => screen.getByText(label, { selector: "dt" }).parentElement!;
    expect(tile("Servers")).toHaveTextContent("10");
    expect(tile("Reachable")).toHaveTextContent("5");
    expect(tile("Unreachable")).toHaveTextContent("2");
    expect(tile("Not monitored")).toHaveTextContent("1");
    expect(tile("Not checked yet")).toHaveTextContent("2");
  });
});

describe("ViewSwitch", () => {
  it("marks the active view and asks for the other one", async () => {
    const onChange = vi.fn();
    render(<ViewSwitch view="cards" onChange={onChange} />);
    const group = screen.getByRole("group", { name: "View" });
    expect(within(group).getByRole("button", { name: "Cards" })).toHaveAttribute("aria-pressed", "true");
    expect(within(group).getByRole("button", { name: "Table" })).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(screen.getByRole("button", { name: "Table" }));
    expect(onChange).toHaveBeenCalledWith("table");
  });
});

describe("ServerCard", () => {
  const track = () => {};

  it("shows the values of a reachable server, with the name linking to its page", () => {
    const s = server("web-01", "reachable");
    const { container } = render(<ServerCard server={s} vitals={vitals(s.id)} now={NOW} track={track} />);
    expect(screen.getByRole("link", { name: "web-01" })).toHaveAttribute("href", "/servers/id-web-01");
    expect(screen.getByText("Reachable")).toBeInTheDocument();
    expect(screen.getByText("Production")).toBeInTheDocument();
    expect(screen.getByText("42%")).toBeInTheDocument();
    expect(screen.getByText("61%")).toBeInTheDocument();
    expect(screen.getByText("1.25")).toBeInTheDocument();
    expect(container.querySelector("[data-server-id]")).toHaveAttribute("data-server-id", "id-web-01");
  });

  it("hands its element to track", () => {
    const s = server("web-01", "reachable");
    const tracked = vi.fn();
    render(<ServerCard server={s} vitals={vitals(s.id)} now={NOW} track={tracked} />);
    expect(tracked.mock.calls[0][0]).toHaveAttribute("data-server-id", "id-web-01");
  });

  it("shows dashes for values six minutes old", () => {
    const s = server("web-01", "reachable");
    render(<ServerCard server={s} vitals={vitals(s.id, 6 * 60_000)} now={NOW} track={track} />);
    expect(screen.queryByText("42%")).not.toBeInTheDocument();
    expect(screen.getByText("CPU").nextElementSibling).toHaveTextContent("—");
  });

  it("greys the last values of an unreachable server and says why", () => {
    const s = server("web-01", "unreachable", { reason: "unreachable" });
    render(<ServerCard server={s} vitals={vitals(s.id)} now={NOW} track={track} />);
    expect(screen.getByText("The server did not answer.")).toBeInTheDocument();
    expect(screen.getByText("42%").closest(".opacity-60")).not.toBeNull();
  });

  it("says a server is not monitored, with the reason", () => {
    const s = server("web-01", "not_monitored", { reason: "host_key_not_pinned" });
    render(<ServerCard server={s} vitals={undefined} now={NOW} track={track} />);
    expect(screen.getAllByText("Not monitored").length).toBeGreaterThan(0);
    expect(screen.getByText("The host key is not pinned yet.")).toBeInTheDocument();
    expect(screen.queryByText("CPU")).not.toBeInTheDocument();
  });

  it("says Windows servers are not monitored yet", () => {
    const s = server("win-01", "not_monitored", { os: "windows", reason: "not_an_ssh_server" });
    render(<ServerCard server={s} vitals={undefined} now={NOW} track={track} />);
    expect(screen.getByText("Windows servers are not monitored yet.")).toBeInTheDocument();
  });

  it("says the collector has not looked at a new server yet", () => {
    const s = server("web-01", null);
    render(<ServerCard server={s} vitals={undefined} now={NOW} track={track} />);
    expect(screen.getByText("The collector has not looked at this server yet.")).toBeInTheDocument();
  });
});

describe("ServerRows", () => {
  it("renders one row per server with its link and CPU, dashes when not monitored, grey when unreachable", () => {
    const up = server("web-01", "reachable");
    const down = server("web-02", "unreachable", { reason: "unreachable" });
    const off = server("win-01", "not_monitored", { os: "windows" });
    const tracked = vi.fn();
    const downVitals = vitals(down.id);
    downVitals.overview.cpu = 17;
    render(
      <ServerRows
        servers={[down, up, off]}
        vitalsOf={{ [up.id]: vitals(up.id), [down.id]: downVitals }}
        now={NOW}
        track={tracked}
      />,
    );
    const rows = screen.getAllByRole("row").slice(1);
    expect(rows.map((r) => r.getAttribute("data-server-id"))).toEqual(["id-web-02", "id-web-01", "id-win-01"]);
    expect(screen.getAllByRole("columnheader").map((h) => h.textContent)).toEqual([
      "Name",
      "Status",
      "CPU",
      "Memory",
      "Disk",
      "Load",
      "Network",
    ]);
    expect(within(rows[1]).getByRole("link", { name: "web-01" })).toHaveAttribute("href", "/servers/id-web-01");
    expect(within(rows[1]).getByText("42%")).toBeInTheDocument();
    expect(rows[0]).toHaveClass("opacity-60");
    expect(within(rows[0]).getByText("17%")).toBeInTheDocument();
    expect(within(rows[2]).getAllByText("—")).toHaveLength(5);
    expect(tracked).toHaveBeenCalledTimes(3);
  });
});
