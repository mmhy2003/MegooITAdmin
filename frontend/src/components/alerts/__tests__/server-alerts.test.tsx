import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ServerAlertBanner } from "@/components/alerts/server-alert-banner";
import { ServerAlertsTab } from "@/components/alerts/server-alerts-tab";
import type { Alert } from "@/lib/alerts";
import { ApiError, apiFetch } from "@/lib/api";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), apiFetch: vi.fn() }));

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

const MEMORY = alertOf("a-2", {
  metric: "mem.used_percent",
  severity: "warning",
  instance: "",
  rule_name: "Memory almost full",
  value: 91.5,
});

function rowIds(element: HTMLElement = document.body): (string | null)[] {
  return [...element.querySelectorAll("[data-alert-id]")].map((row) => row.getAttribute("data-alert-id"));
}

beforeEach(() => {
  vi.mocked(apiFetch).mockReset();
});

describe("ServerAlertBanner", () => {
  it("names each firing alert with its severity and links to the Alerts tab", () => {
    render(<ServerAlertBanner serverId="s-1" alerts={[alertOf("a-1"), MEMORY]} />);
    const banner = screen.getByRole("alert");
    expect(banner).toHaveClass("text-destructive");
    expect(within(banner).getByText("2 alerts firing")).toBeInTheDocument();
    const items = within(banner).getAllByRole("listitem");
    expect(items.map((item) => item.textContent)).toEqual([
      "Criticalweb-01: / is 93.3% full",
      "Warningweb-01: memory is 91.5% used",
    ]);
    expect(within(banner).getByRole("link", { name: "Show alerts" })).toHaveAttribute(
      "href",
      "/servers/s-1?tab=alerts",
    );
  });

  it("says one alert in the singular", () => {
    render(<ServerAlertBanner serverId="s-1" alerts={[alertOf("a-1")]} />);
    expect(screen.getByText("1 alert firing")).toBeInTheDocument();
  });

  it("shows nothing while no alert fires", () => {
    const { container } = render(<ServerAlertBanner serverId="s-1" alerts={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("ServerAlertsTab", () => {
  it("shows the firing alerts first, then the history, without a Server column", () => {
    render(<ServerAlertsTab serverId="s-1" alerts={[alertOf("a-1"), ...closed(2)]} />);
    const firing = within(screen.getByRole("region", { name: "Firing" }));
    const history = within(screen.getByRole("region", { name: "History" }));
    expect(rowIds(firing.getByRole("table"))).toEqual(["a-1"]);
    expect(rowIds(history.getByRole("table"))).toEqual(["c-0", "c-1"]);
    expect(
      screen
        .getByRole("heading", { name: "Firing" })
        .compareDocumentPosition(screen.getByRole("heading", { name: "History" })) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(screen.queryByRole("columnheader", { name: "Server" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Show more" })).not.toBeInTheDocument();
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("says when nothing fires and nothing has closed", () => {
    render(<ServerAlertsTab serverId="s-1" alerts={[]} />);
    expect(screen.getByText("No alerts are firing.")).toBeInTheDocument();
    expect(screen.getByText("No alert has closed on this server yet.")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("shows more history from before the last resolved alert of a full page", async () => {
    const first = closed(50);
    vi.mocked(apiFetch).mockResolvedValue(closed(3, 50));
    render(<ServerAlertsTab serverId="s-1" alerts={[alertOf("a-1"), ...first]} />);
    await userEvent.click(screen.getByRole("button", { name: "Show more" }));

    const history = screen.getByRole("region", { name: "History" });
    await waitFor(() => expect(rowIds(history)).toHaveLength(53));
    expect(rowIds(history).slice(48)).toEqual(["c-48", "c-49", "c-50", "c-51", "c-52"]);
    expect(apiFetch).toHaveBeenCalledWith(
      `/servers/s-1/alerts?${new URLSearchParams({ before: first[49].resolved_at! })}`,
    );
    expect(screen.queryByRole("button", { name: "Show more" })).not.toBeInTheDocument();
  });

  it("says when more history could not be read", async () => {
    vi.mocked(apiFetch).mockRejectedValue(new ApiError(503, "unavailable"));
    render(<ServerAlertsTab serverId="s-1" alerts={closed(50)} />);
    await userEvent.click(screen.getByRole("button", { name: "Show more" }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(rowIds()).toHaveLength(50);
  });
});
