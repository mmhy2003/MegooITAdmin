import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AlertBell } from "@/components/shell/alert-bell";
import { useRefresh } from "@/hooks/use-refresh";
import type { Alert, AlertEvent, AlertEvents } from "@/lib/alerts";
import { apiFetch } from "@/lib/api";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), apiFetch: vi.fn() }));
vi.mock("@/hooks/use-refresh", () => ({ useRefresh: vi.fn() }));

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

function eventOf(id: string, alert: Partial<Alert> = {}, kind: AlertEvent["kind"] = "fired"): AlertEvent {
  return { id, kind, at: "2026-11-27T10:00:00Z", alert: alertOf(alert) };
}

const TEN = Array.from({ length: 10 }, (_, i) =>
  eventOf(`e-${i}`, { id: `a-${i}`, server_id: `s-${i}`, server_name: `web-${i}` }),
);

function mockApi(answer: AlertEvents) {
  vi.mocked(apiFetch).mockImplementation(async (path: string, init?: { method?: string }) => {
    if (path === "/alerts/seen" && init?.method === "POST") return undefined;
    if (path === "/alerts/events") return answer;
    throw new Error(`unexpected ${path}`);
  });
}

const seenCalls = () => vi.mocked(apiFetch).mock.calls.filter(([path]) => path === "/alerts/seen");
const bell = (name: string | RegExp) => screen.findByRole("button", { name });

async function refreshNow() {
  const calls = vi.mocked(useRefresh).mock.calls;
  await act(async () => {
    calls[calls.length - 1][0]();
  });
}

beforeEach(() => {
  vi.mocked(apiFetch).mockReset();
  vi.mocked(useRefresh).mockReset();
});

describe("AlertBell", () => {
  it("shows the number of unseen events", async () => {
    mockApi({ unseen: 3, firing: 1, events: TEN.slice(0, 3) });
    render(<AlertBell />);
    expect(await bell("Alerts, 3 new")).toHaveTextContent("3");
    expect(apiFetch).toHaveBeenCalledWith("/alerts/events");
  });

  it("shows 99+ above 99", async () => {
    mockApi({ unseen: 120, firing: 0, events: TEN });
    render(<AlertBell />);
    expect(await bell("Alerts, 120 new")).toHaveTextContent("99+");
  });

  it("shows no count when nothing is unseen", async () => {
    mockApi({ unseen: 0, firing: 0, events: TEN });
    render(<AlertBell />);
    await waitFor(() => expect(apiFetch).toHaveBeenCalled());
    expect(await bell("Alerts, 0 new")).toHaveTextContent(/^$/);
  });

  it("lists the events, each a link to its server's Alerts tab", async () => {
    const user = userEvent.setup();
    const events = [
      eventOf("e-1", { server_id: "s-7", severity: "warning" }),
      eventOf("e-2", { server_id: "s-8", state: "resolved", last_value: 80 }, "resolved"),
      ...TEN.slice(2),
    ];
    mockApi({ unseen: 0, firing: 1, events });
    render(<AlertBell />);
    await user.click(await bell("Alerts, 0 new"));

    const dialog = await screen.findByRole("dialog");
    const links = within(dialog).getAllByRole("link");
    expect(links).toHaveLength(10);
    expect(links[0]).toHaveAttribute("href", "/servers/s-7?tab=alerts");
    expect(links[0]).toHaveTextContent("web-01: / is 93.3% full");
    expect(links[0]).toHaveTextContent("Warning");
    expect(links[1]).toHaveAttribute("href", "/servers/s-8?tab=alerts");
    expect(links[1]).toHaveTextContent("Resolved: web-01: / is 80.0% full");
    expect(links[1]).toHaveTextContent("Critical");
    expect(within(links[0]).getByText(/2026|\d{1,2}:\d{2}/)).toBeInTheDocument();
  });

  it("says so when there are no events", async () => {
    const user = userEvent.setup();
    mockApi({ unseen: 0, firing: 0, events: [] });
    render(<AlertBell />);
    await user.click(await bell("Alerts, 0 new"));
    expect(await within(await screen.findByRole("dialog")).findByText("No alert events yet.")).toBeInTheDocument();
  });

  it("marks the events seen once when it is opened", async () => {
    const user = userEvent.setup();
    mockApi({ unseen: 2, firing: 1, events: TEN.slice(0, 2) });
    render(<AlertBell />);
    await user.click(await bell("Alerts, 2 new"));
    await screen.findByRole("dialog");

    expect(seenCalls()).toEqual([["/alerts/seen", { method: "POST" }]]);
    const button = screen.getByRole("button", { name: "Alerts, 0 new" });
    expect(button).toHaveTextContent(/^$/);

    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await user.click(button);
    await screen.findByRole("dialog");
    expect(seenCalls()).toHaveLength(1);
  });

  it("re-reads the events in the background", async () => {
    mockApi({ unseen: 0, firing: 0, events: [] });
    render(<AlertBell />);
    await bell("Alerts, 0 new");

    mockApi({ unseen: 4, firing: 1, events: TEN.slice(0, 4) });
    await refreshNow();

    expect(await bell("Alerts, 4 new")).toHaveTextContent("4");
    expect(apiFetch).toHaveBeenCalledWith("/alerts/events", { background: true });
    expect(vi.mocked(useRefresh).mock.calls.at(-1)?.[1]).toBe(true);
  });
});
