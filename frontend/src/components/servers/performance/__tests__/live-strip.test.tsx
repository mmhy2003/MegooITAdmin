import { act, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { installFakeWebSocket, type FakeWebSocket } from "@/__tests__/helpers/fake-websocket";
import { server } from "@/components/dashboard/__tests__/fixtures";
import { LiveStrip } from "@/components/servers/performance/live-strip";
import { useRefresh } from "@/hooks/use-refresh";
import { apiFetch } from "@/lib/api";
import { emptyTrend, type OverviewRead, type ServerOverviewRead } from "@/lib/metrics";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), apiFetch: vi.fn() }));
vi.mock("@/lib/auth/navigate");
vi.mock("@/hooks/use-refresh", () => ({ useRefresh: vi.fn() }));

const DB = server("db-01", "reachable");

let Socket: typeof FakeWebSocket;

/** An overview read of DB taken `ageMs` ago. */
function overviewOf(cpu: number, ageMs = 1_000): ServerOverviewRead {
  const time = Date.now() - ageMs;
  const trend = emptyTrend(time);
  return {
    server_id: DB.id,
    time: new Date(time).toISOString(),
    cpu,
    mem: 61,
    load: 0.5,
    disk: { mount: "/var", percent: 30 },
    rx: 100,
    tx: 200,
    trend: { start: new Date(trend.start).toISOString(), cpu: trend.cpu, mem: trend.mem },
  };
}

function mockOverview(read: () => ServerOverviewRead) {
  vi.mocked(apiFetch).mockImplementation(async (path: string) => {
    if (path === `/metrics/overview?server_id=${DB.id}`) return { servers: [read()], denied: [] } as OverviewRead;
    throw new Error(`unexpected ${path}`);
  });
}

function overviewCalls() {
  return vi.mocked(apiFetch).mock.calls.filter(([path]) => path.startsWith("/metrics/overview?"));
}

function item(label: string): HTMLElement {
  return screen.getByText(label, { selector: "dt" }).nextElementSibling as HTMLElement;
}

function socket(): FakeWebSocket {
  return Socket.instances[Socket.instances.length - 1];
}

beforeEach(() => {
  vi.mocked(apiFetch).mockReset();
  vi.mocked(useRefresh).mockReset();
  Socket = installFakeWebSocket();
  vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
});

describe("LiveStrip", () => {
  it("fills CPU and memory from the overview read", async () => {
    mockOverview(() => overviewOf(42));
    render(<LiveStrip server={DB} />);

    expect(screen.getByRole("heading", { name: "Live" })).toBeInTheDocument();
    expect(await screen.findByText("42%")).toBeInTheDocument();
    expect(item("CPU")).toHaveTextContent("42%");
    expect(item("Memory")).toHaveTextContent("61%");
    expect(overviewCalls()[0]).toEqual([`/metrics/overview?server_id=${DB.id}`, { background: false }]);
  });

  it("subscribes to the server and updates CPU from an overview message", async () => {
    mockOverview(() => overviewOf(42));
    render(<LiveStrip server={DB} />);
    await screen.findByText("42%");
    const ws = socket();
    await act(async () => ws.open());
    expect(ws.sent).toContainEqual({ type: "subscribe", view: "overview", server_ids: [DB.id] });
    expect(screen.getByRole("status")).toHaveTextContent("Live");

    act(() =>
      ws.receive({
        type: "overview",
        server_id: DB.id,
        time: new Date().toISOString(),
        cpu: 77,
        mem: null,
        load: null,
        disk: null,
        rx: null,
        tx: null,
      }),
    );
    expect(item("CPU")).toHaveTextContent("77%");
    expect(item("Memory")).toHaveTextContent("61%");
  });

  it("ignores a message of another server", async () => {
    mockOverview(() => overviewOf(42));
    render(<LiveStrip server={DB} />);
    await screen.findByText("42%");
    const ws = socket();
    await act(async () => ws.open());

    act(() =>
      ws.receive({
        type: "overview",
        server_id: "someone-else",
        time: new Date().toISOString(),
        cpu: 99,
        mem: 99,
        load: 9,
        disk: null,
        rx: null,
        tx: null,
      }),
    );
    expect(item("CPU")).toHaveTextContent("42%");
  });

  it("reads again in the background when the socket opens, and every refresh", async () => {
    let cpu = 42;
    mockOverview(() => overviewOf(cpu));
    render(<LiveStrip server={DB} />);
    await screen.findByText("42%");

    cpu = 55;
    await act(async () => socket().open());
    expect(overviewCalls()).toHaveLength(2);
    expect(overviewCalls()[1][1]).toEqual({ background: true });
    expect(item("CPU")).toHaveTextContent("55%");

    cpu = 60;
    await act(async () => vi.mocked(useRefresh).mock.lastCall![0]());
    expect(overviewCalls()[2][1]).toEqual({ background: true });
    expect(item("CPU")).toHaveTextContent("60%");
  });

  it("keeps newer live values over an older read", async () => {
    let read = overviewOf(42);
    mockOverview(() => read);
    render(<LiveStrip server={DB} />);
    await screen.findByText("42%");
    const ws = socket();
    act(() => ws.receive({ ...overviewOf(77, 0), type: "overview", trend: undefined }));
    expect(item("CPU")).toHaveTextContent("77%");

    read = overviewOf(10, 60_000);
    await act(async () => ws.open());
    expect(item("CPU")).toHaveTextContent("77%");
  });

  it("links to the Performance tab", () => {
    mockOverview(() => overviewOf(42));
    render(<LiveStrip server={DB} />);
    expect(screen.getByRole("link", { name: "Performance" })).toHaveAttribute(
      "href",
      `/servers/${DB.id}?tab=performance`,
    );
  });

  it("shows dashes when the newest values are stale", async () => {
    mockOverview(() => overviewOf(42, 10 * 60_000));
    render(<LiveStrip server={DB} />);
    await act(async () => {});

    expect(overviewCalls()).toHaveLength(1);
    expect(item("CPU")).toHaveTextContent(/^—$/);
    expect(item("Memory")).toHaveTextContent(/^—$/);
  });

  it("greys the values while the server is unreachable", async () => {
    mockOverview(() => overviewOf(42));
    const { container } = render(<LiveStrip server={server("db-01", "unreachable")} />);
    await screen.findByText("42%");
    expect(container.querySelector(".opacity-60")).toContainElement(item("CPU"));
  });
});
