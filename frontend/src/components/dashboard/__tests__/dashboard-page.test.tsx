import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useRouter, useSearchParams } from "next/navigation";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { installFakeWebSocket, type FakeWebSocket } from "@/__tests__/helpers/fake-websocket";
import { installIntersectionObserver } from "@/__tests__/helpers/intersection-observer";
import { DashboardPage } from "@/components/dashboard/dashboard-page";
import { useRefresh } from "@/hooks/use-refresh";
import type { ServerGroup } from "@/lib/access";
import type { Alert } from "@/lib/alerts";
import { apiFetch } from "@/lib/api";
import { emptyTrend, type OverviewRead, type ServerOverviewRead } from "@/lib/metrics";
import type { Server } from "@/lib/servers";
import { server } from "./fixtures";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), apiFetch: vi.fn() }));
vi.mock("@/lib/auth/navigate");
vi.mock("@/hooks/use-refresh", () => ({ useRefresh: vi.fn() }));

const GROUP: ServerGroup = {
  id: "g",
  name: "Production",
  description: null,
  created_at: "2026-11-01T00:00:00Z",
  member_count: 1,
  server_count: 10,
  can_manage: false,
};

let Socket: typeof FakeWebSocket;
let io: ReturnType<typeof installIntersectionObserver>;
let replace: ReturnType<typeof vi.fn>;

/** An overview read of `id`, taken a second ago, with one CPU value in the last trend slot. */
function overviewOf(id: string, cpu: number): ServerOverviewRead {
  const time = Date.now() - 1_000;
  const trend = emptyTrend(time);
  trend.cpu[trend.cpu.length - 1] = cpu;
  return {
    server_id: id,
    time: new Date(time).toISOString(),
    cpu,
    mem: 50,
    load: 0.5,
    disk: { mount: "/", percent: 30 },
    rx: 100,
    tx: 200,
    trend: { start: new Date(trend.start).toISOString(), cpu: trend.cpu, mem: trend.mem },
  };
}

function idsOf(path: string): string[] {
  return new URLSearchParams(path.split("?")[1]).getAll("server_id");
}

/** A firing alert of the disk rule on `/` of the server `id`, named after the id so its link is not the card's. */
function firingOn(id: string, alertId: string): Alert {
  return {
    id: alertId,
    server_id: id,
    server_name: id,
    group_id: "g",
    group_name: "Production",
    rule_id: "r",
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
    last_value: 93.25,
    peak_value: 93.25,
  };
}

function mockApi({
  groups = [GROUP],
  servers = [] as Server[],
  overview = (ids: string[]): OverviewRead => ({ servers: [], denied: ids }),
  firing = [] as Alert[],
  closed = [] as Alert[],
} = {}) {
  vi.mocked(apiFetch).mockImplementation(async (path: string) => {
    if (path === "/server-groups") return groups;
    if (path === "/server-tags") return [];
    if (path.startsWith("/alerts?")) return path.includes("state=firing") ? firing : closed;
    if (path.startsWith("/metrics/overview?")) return overview(idsOf(path));
    if (path.startsWith("/servers")) return servers;
    throw new Error(`unexpected ${path}`);
  });
}

function query(search: string) {
  vi.mocked(useSearchParams).mockReturnValue(
    new URLSearchParams(search) as unknown as ReturnType<typeof useSearchParams>,
  );
}

function socket(): FakeWebSocket {
  return Socket.instances[Socket.instances.length - 1];
}

function subscribes(ws: FakeWebSocket) {
  return ws.sent.filter((frame) => (frame as { type: string }).type === "subscribe") as {
    view: string;
    server_ids: string[];
  }[];
}

function overviewCalls() {
  return vi.mocked(apiFetch).mock.calls.filter(([path]) => path.startsWith("/metrics/overview?"));
}

function alertCalls() {
  return vi.mocked(apiFetch).mock.calls.filter(([path]) => path.startsWith("/alerts?"));
}

function listCalls() {
  return vi.mocked(apiFetch).mock.calls.filter(([path]) => path.startsWith("/servers"));
}

function card(name: string): HTMLElement {
  return screen.getByRole("link", { name }).closest("[data-server-id]") as HTMLElement;
}

async function show(ids: string[]) {
  await act(async () => io.show(ids));
}

const TEN = Array.from({ length: 10 }, (_, i) => server(`fleet-${String(i + 1).padStart(2, "0")}`, "reachable"));

beforeEach(() => {
  vi.mocked(apiFetch).mockReset();
  vi.mocked(useRefresh).mockReset();
  Socket = installFakeWebSocket();
  io = installIntersectionObserver();
  vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
  replace = vi.fn();
  vi.mocked(useRouter).mockReturnValue({ push: vi.fn(), replace, refresh: vi.fn() } as unknown as ReturnType<
    typeof useRouter
  >);
  query("");
});

describe("DashboardPage", () => {
  it("updates each of ten servers from socket messages without a reload", async () => {
    mockApi({ servers: TEN });
    render(<DashboardPage />);
    expect(await screen.findByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
    await screen.findByRole("link", { name: "fleet-10" });
    const ids = TEN.map((s) => s.id);
    await show(ids);

    const ws = socket();
    act(() => ws.open());
    expect(subscribes(ws).at(-1)).toEqual({ type: "subscribe", view: "overview", server_ids: [...ids].sort() });
    expect(screen.getByRole("status")).toHaveTextContent("Live");

    act(() => {
      TEN.forEach((s, index) =>
        ws.receive({
          type: "overview",
          server_id: s.id,
          time: new Date().toISOString(),
          cpu: 10 + index,
          mem: 40,
          load: 0.2,
          disk: { mount: "/", percent: 20 },
          rx: 1,
          tx: 2,
        }),
      );
    });

    TEN.forEach((s, index) => {
      expect(within(card(s.name)).getByText(`${10 + index}%`)).toBeInTheDocument();
    });
    expect(listCalls()).toHaveLength(1);
  });

  it("subscribes only to the servers on screen, and again when others scroll in", async () => {
    mockApi({ servers: TEN });
    render(<DashboardPage />);
    await screen.findByRole("link", { name: "fleet-10" });
    await show(TEN.slice(0, 3).map((s) => s.id));
    const ws = socket();
    act(() => ws.open());
    expect(subscribes(ws).at(-1)?.server_ids).toEqual(["id-fleet-01", "id-fleet-02", "id-fleet-03"]);

    await show(TEN.slice(4, 6).map((s) => s.id));
    expect(subscribes(ws).at(-1)).toEqual({
      type: "subscribe",
      view: "overview",
      server_ids: ["id-fleet-05", "id-fleet-06"],
    });
    expect(Socket.instances).toHaveLength(1);
  });

  it("puts unreachable servers first, then reachable ones, then the rest, each by name", async () => {
    mockApi({
      servers: [
        server("b-up", "reachable"),
        server("z-off", "not_monitored", { reason: "host_key_not_pinned" }),
        server("a-up", "reachable"),
        server("y-down", "unreachable", { reason: "unreachable" }),
        server("c-new", null),
        server("x-down", "unreachable", { reason: "unreachable" }),
      ],
    });
    render(<DashboardPage />);
    await screen.findByRole("link", { name: "a-up" });
    const names = [...document.querySelectorAll("[data-server-id]")].map((e) => e.getAttribute("data-server-id"));
    expect(names).toEqual(["id-x-down", "id-y-down", "id-a-up", "id-b-up", "id-c-new", "id-z-off"]);
  });

  it("greys the last values of an unreachable server with the reason, and says when one is not monitored", async () => {
    const down = server("down-01", "unreachable", { reason: "unreachable" });
    const off = server("off-01", "not_monitored", { reason: "host_key_not_pinned" });
    mockApi({
      servers: [down, off],
      overview: (ids) => ({ servers: ids.map((id) => overviewOf(id, 33)), denied: [] }),
    });
    render(<DashboardPage />);
    await screen.findByRole("link", { name: "down-01" });
    await show([down.id, off.id]);

    const downCard = within(card("down-01"));
    expect(await downCard.findByText("33%")).toBeInTheDocument();
    expect(downCard.getByText("33%").closest(".opacity-60")).not.toBeNull();
    expect(downCard.getByText("The server did not answer.")).toBeInTheDocument();
    const offCard = within(card("off-01"));
    expect(offCard.getAllByText("Not monitored").length).toBeGreaterThan(0);
    expect(offCard.getByText("The host key is not pinned yet.")).toBeInTheDocument();
  });

  it("keeps the filters when switching to the table, and the table when changing the group", async () => {
    const other: ServerGroup = { ...GROUP, id: "h", name: "Staging" };
    mockApi({ groups: [GROUP, other], servers: [server("web-01", "reachable")] });
    query("group=g");
    const { unmount } = render(<DashboardPage />);
    await screen.findByRole("link", { name: "web-01" });
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Table" }));
    expect(replace).toHaveBeenCalledWith("/?group=g&view=table");
    unmount();

    query("group=g&view=table");
    render(<DashboardPage />);
    expect(await screen.findByRole("table")).toBeInTheDocument();
    expect(screen.getByRole("row", { name: /web-01/ })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("combobox", { name: "Group" }));
    await userEvent.click(await screen.findByRole("option", { name: "Staging" }));
    expect(replace).toHaveBeenLastCalledWith("/?group=h&view=table");
  });

  it("subscribes to the table rows on screen too", async () => {
    mockApi({ servers: TEN });
    query("view=table");
    render(<DashboardPage />);
    await screen.findByRole("row", { name: /fleet-10/ });
    await show(["id-fleet-02", "id-fleet-07"]);
    const ws = socket();
    act(() => ws.open());
    expect(subscribes(ws).at(-1)?.server_ids).toEqual(["id-fleet-02", "id-fleet-07"]);
  });

  it("reads the overview for cards that come on screen, and again after a reconnect", async () => {
    const [a, b] = TEN;
    mockApi({
      servers: [a, b],
      overview: (ids) => ({ servers: ids.map((id) => overviewOf(id, 27)), denied: [] }),
    });
    render(<DashboardPage />);
    await screen.findByRole("link", { name: a.name });
    expect(overviewCalls()).toHaveLength(0);

    await show([a.id]);
    await waitFor(() => expect(overviewCalls()).toHaveLength(1));
    expect(idsOf(overviewCalls()[0][0])).toEqual([a.id]);
    const aCard = within(card(a.name));
    expect(await aCard.findByText("27%")).toBeInTheDocument();
    expect(aCard.getByRole("img", { name: "CPU, last 5 minutes" }).querySelector("path")).not.toBeNull();
    expect(within(card(b.name)).queryByText("27%")).not.toBeInTheDocument();

    const ws = socket();
    await act(async () => ws.open());
    expect(overviewCalls()).toHaveLength(2);
    expect(overviewCalls()[1][1]).toEqual({ background: true });

    vi.useFakeTimers({ toFake: ["setTimeout"] });
    try {
      act(() => ws.drop(1006));
      await act(async () => vi.advanceTimersByTime(1000));
    } finally {
      vi.useRealTimers();
    }
    await act(async () => socket().open());
    expect(socket()).not.toBe(ws);
    expect(overviewCalls()).toHaveLength(3);
    expect(idsOf(overviewCalls()[2][0])).toEqual([a.id]);
  });

  it("keeps a newer live value when an older overview read arrives", async () => {
    const [a] = TEN;
    let answer: (read: OverviewRead) => void = () => {};
    vi.mocked(apiFetch).mockImplementation(async (path: string) => {
      if (path === "/server-groups") return [GROUP];
      if (path === "/server-tags") return [];
      if (path.startsWith("/alerts?")) return [];
      if (path.startsWith("/metrics/overview?")) return new Promise((resolve) => (answer = resolve));
      return [a];
    });
    render(<DashboardPage />);
    await screen.findByRole("link", { name: a.name });
    await show([a.id]);
    const ws = socket();
    act(() => ws.open());
    act(() =>
      ws.receive({
        type: "overview",
        server_id: a.id,
        time: new Date().toISOString(),
        cpu: 88,
        mem: 40,
        load: 0.2,
        disk: null,
        rx: 1,
        tx: 2,
      }),
    );
    await act(async () => answer({ servers: [overviewOf(a.id, 12)], denied: [] }));
    expect(within(card(a.name)).getByText("88%")).toBeInTheDocument();
    expect(within(card(a.name)).queryByText("12%")).not.toBeInTheDocument();
  });

  it("re-reads the list and the overview in the background every refresh", async () => {
    const [a] = TEN;
    mockApi({ servers: [a], overview: (ids) => ({ servers: ids.map((id) => overviewOf(id, 5)), denied: [] }) });
    render(<DashboardPage />);
    await screen.findByRole("link", { name: a.name });
    await show([a.id]);
    await waitFor(() => expect(overviewCalls()).toHaveLength(1));
    await act(async () => vi.mocked(useRefresh).mock.lastCall![0]());
    expect(listCalls().at(-1)).toEqual(["/servers", { background: true }]);
    expect(alertCalls().at(-1)).toEqual(["/alerts?state=firing", { background: true }]);
    expect(overviewCalls().at(-1)).toEqual([`/metrics/overview?server_id=${a.id}`, { background: true }]);
  });

  it("says when there is no group, no server, or none matching the filters", async () => {
    mockApi({ groups: [] });
    const { unmount } = render(<DashboardPage />);
    expect(await screen.findByText(/You do not see any server group yet/)).toBeInTheDocument();
    unmount();

    mockApi();
    const second = render(<DashboardPage />);
    expect(await screen.findByText("No servers yet.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /servers/i })).toHaveAttribute("href", "/servers");
    second.unmount();

    query("group=g");
    render(<DashboardPage />);
    expect(await screen.findByText("No servers match these filters.")).toBeInTheDocument();
  });

  it("counts the firing alerts, lists them under the summary and marks their servers", async () => {
    const [a, b, c] = TEN;
    mockApi({
      servers: [a, b, c],
      firing: [firingOn(a.id, "x-1"), firingOn(a.id, "x-2"), firingOn(c.id, "x-3")],
    });
    const { unmount } = render(<DashboardPage />);
    await screen.findByRole("link", { name: b.name });
    expect(alertCalls()[0]).toEqual(["/alerts?state=firing"]);
    const tile = screen.getByText("Firing alerts", { selector: "dt" }).parentElement!;
    expect(tile).toHaveTextContent("3");

    const alerts = screen.getByRole("heading", { name: "Alerts" }).closest("[data-slot=card]")!;
    const dashboard = screen.getByRole("heading", { name: "Dashboard" }).closest("[data-slot=card]")!;
    expect(dashboard.nextElementSibling).toBe(alerts);
    expect(within(alerts as HTMLElement).getByRole("tab", { name: "Firing (3)" })).toBeInTheDocument();
    expect(alerts.querySelectorAll("[data-alert-id]")).toHaveLength(3);

    expect(within(card(a.name)).getByText("2 alerts")).toBeInTheDocument();
    expect(within(card(c.name)).getByText("1 alert")).toBeInTheDocument();
    expect(within(card(b.name)).queryByText(/alerts?$/)).not.toBeInTheDocument();
    unmount();

    query("view=table");
    render(<DashboardPage />);
    await screen.findByRole("link", { name: a.name });
    expect(card(a.name).tagName).toBe("TR");
    expect(within(card(a.name)).getByText("2 alerts")).toBeInTheDocument();
  });

  it("reads the firing alerts and their history of the filtered servers", async () => {
    mockApi({ servers: [server("web-01", "reachable")], closed: [] });
    query("group=g&tag=web");
    render(<DashboardPage />);
    await screen.findByRole("link", { name: "web-01" });
    expect(alertCalls()[0]).toEqual(["/alerts?group_id=g&tag=web&state=firing"]);
    expect(screen.getByText("No alerts are firing.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "History" }));
    expect(await screen.findByText("No alerts in the last 30 days.")).toBeInTheDocument();
    expect(alertCalls().at(-1)).toEqual(["/alerts?group_id=g&tag=web&state=closed"]);
  });
});
