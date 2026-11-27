import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AlertsCard } from "@/components/alerts/alerts-card";
import { type Alert, alertsPath } from "@/lib/alerts";
import { apiFetch } from "@/lib/api";
import type { ServerFilters } from "@/lib/servers";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), apiFetch: vi.fn() }));

const ALL: ServerFilters = { group: null, tags: [] };

function alertOf(id: string, fields: Partial<Alert> = {}): Alert {
  return {
    id,
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

/** `count` resolved alerts, the newest first, each resolved one minute before the one above it. */
function closed(count: number, from = 0): Alert[] {
  return Array.from({ length: count }, (_, i) =>
    alertOf(`c-${from + i}`, {
      state: "resolved",
      resolved_at: new Date(Date.parse("2026-11-27T09:00:00Z") - (from + i) * 60_000).toISOString(),
    }),
  );
}

function rowIds(): (string | null)[] {
  return [...document.querySelectorAll("[data-alert-id]")].map((row) => row.getAttribute("data-alert-id"));
}

beforeEach(() => {
  vi.mocked(apiFetch).mockReset();
});

describe("AlertsCard", () => {
  it("shows the firing alerts under the Firing tab, without reading anything", () => {
    render(<AlertsCard firing={[alertOf("a-1"), alertOf("a-2", { server_name: "db-01" })]} filters={ALL} />);
    expect(screen.getByRole("heading", { name: "Alerts" })).toBeInTheDocument();
    const tabs = within(screen.getByRole("tablist", { name: "Alerts" })).getAllByRole("tab");
    expect(tabs.map((tab) => tab.textContent)).toEqual(["Firing (2)", "History"]);
    expect(tabs[0]).toHaveAttribute("aria-selected", "true");
    expect(rowIds()).toEqual(["a-1", "a-2"]);
    expect(screen.getByText("db-01: / is 93.3% full")).toBeInTheDocument();
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("says when no alert is firing", () => {
    render(<AlertsCard firing={[]} filters={ALL} />);
    expect(screen.getByRole("tab", { name: "Firing (0)" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("No alerts are firing.")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("reads the history of the filtered servers when it is opened", async () => {
    const filters: ServerFilters = { group: "g-1", tags: ["web"] };
    vi.mocked(apiFetch).mockResolvedValue(closed(2));
    render(<AlertsCard firing={[alertOf("a-1")]} filters={filters} />);
    await userEvent.click(screen.getByRole("tab", { name: "History" }));
    expect(screen.getByRole("tab", { name: "History" })).toHaveAttribute("aria-selected", "true");
    await waitFor(() => expect(rowIds()).toEqual(["c-0", "c-1"]));
    expect(apiFetch).toHaveBeenCalledWith(alertsPath("closed", filters));
    expect(apiFetch).toHaveBeenCalledWith("/alerts?group_id=g-1&tag=web&state=closed");
    expect(screen.getAllByText("Resolved").length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: "Show more" })).not.toBeInTheDocument();
  });

  it("says when nothing was closed in the last 30 days", async () => {
    vi.mocked(apiFetch).mockResolvedValue([]);
    render(<AlertsCard firing={[]} filters={ALL} />);
    await userEvent.click(screen.getByRole("tab", { name: "History" }));
    expect(await screen.findByText("No alerts in the last 30 days.")).toBeInTheDocument();
  });

  it("shows more history from before the last resolved alert of a full page", async () => {
    const first = closed(50);
    vi.mocked(apiFetch).mockImplementation(async (path: string) => (path.includes("before=") ? closed(3, 50) : first));
    render(<AlertsCard firing={[]} filters={ALL} />);
    await userEvent.click(screen.getByRole("tab", { name: "History" }));
    await userEvent.click(await screen.findByRole("button", { name: "Show more" }));
    await waitFor(() => expect(rowIds()).toHaveLength(53));
    expect(rowIds().slice(48)).toEqual(["c-48", "c-49", "c-50", "c-51", "c-52"]);
    expect(apiFetch).toHaveBeenLastCalledWith(alertsPath("closed", ALL, first[49].resolved_at!));
    expect(screen.queryByRole("button", { name: "Show more" })).not.toBeInTheDocument();
  });

  it("reads the history again when the filters change", async () => {
    vi.mocked(apiFetch).mockResolvedValue(closed(1));
    const { rerender } = render(<AlertsCard firing={[]} filters={ALL} />);
    await userEvent.click(screen.getByRole("tab", { name: "History" }));
    await waitFor(() => expect(rowIds()).toEqual(["c-0"]));

    const staging: ServerFilters = { group: "g-2", tags: [] };
    vi.mocked(apiFetch).mockResolvedValue(closed(1, 7));
    rerender(<AlertsCard firing={[]} filters={staging} />);
    await waitFor(() => expect(rowIds()).toEqual(["c-7"]));
    expect(apiFetch).toHaveBeenLastCalledWith(alertsPath("closed", staging));
  });

  it("says when the history could not be read", async () => {
    const { ApiError } = await import("@/lib/api");
    vi.mocked(apiFetch).mockRejectedValue(new ApiError(503, "unavailable"));
    render(<AlertsCard firing={[]} filters={ALL} />);
    await userEvent.click(screen.getByRole("tab", { name: "History" }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });
});
