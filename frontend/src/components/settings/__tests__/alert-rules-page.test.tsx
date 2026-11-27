import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AlertRulesPage } from "@/components/settings/alert-rules-page";
import type { AlertRule } from "@/lib/alerts";
import { ApiError, apiFetch } from "@/lib/api";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), apiFetch: vi.fn() }));
vi.mock("@/lib/auth/navigate");

const DISK: AlertRule = {
  id: "r-disk",
  name: "Disk almost full",
  metric: "disk.used_percent",
  comparison: "above",
  threshold: 90,
  duration_seconds: 600,
  severity: "critical",
  server_group_id: null,
  server_group_name: null,
  server_id: null,
  server_name: null,
  enabled: true,
  revision: 1,
  suggested_playbook_id: null,
  firing_count: 2,
  created_at: "2026-11-01T00:00:00Z",
  updated_at: "2026-11-01T00:00:00Z",
};
const MEMORY: AlertRule = {
  ...DISK,
  id: "r-memory",
  name: "Memory on production",
  metric: "mem.used_percent",
  severity: "warning",
  server_group_id: "g-production",
  server_group_name: "production",
  enabled: false,
  firing_count: 1,
};
const DOWN: AlertRule = {
  ...DISK,
  id: "r-down",
  name: "web-1 down",
  metric: "unreachable",
  comparison: null,
  threshold: null,
  duration_seconds: 300,
  server_id: "s-web-1",
  server_name: "web-1",
  firing_count: 0,
};

beforeEach(() => {
  vi.mocked(apiFetch).mockReset();
});

function mockApi(rules: AlertRule[] = [DISK, MEMORY, DOWN]) {
  vi.mocked(apiFetch).mockImplementation(async (path: string, init?: { method?: string }) => {
    if (path.startsWith("/alert-rules/") && init?.method === "PATCH") return DISK;
    if (path.startsWith("/alert-rules/") && init?.method === "DELETE") return undefined;
    if (path === "/alert-rules") return rules;
    throw new Error(`unexpected ${path}`);
  });
}

function listCalls() {
  return vi.mocked(apiFetch).mock.calls.filter(([path, init]) => path === "/alert-rules" && !init).length;
}

describe("AlertRulesPage", () => {
  it("lists each rule with its condition, scope, severity, firing count and switch", async () => {
    mockApi();
    render(<AlertRulesPage />);

    expect(await screen.findByRole("heading", { name: "Alert rules" })).toBeInTheDocument();
    const disk = within(await screen.findByRole("row", { name: /Disk almost full/ }));
    expect(disk.getByText("Space used above 90% for 10 min")).toBeInTheDocument();
    expect(disk.getByText("All servers")).toBeInTheDocument();
    expect(disk.getByText("Critical")).toBeInTheDocument();
    expect(disk.getByText("Firing on 2 servers")).toBeInTheDocument();
    expect(disk.getByRole("switch", { name: "Enabled" })).toBeChecked();
    expect(disk.getByRole("button", { name: "Edit Disk almost full" })).toBeInTheDocument();
    expect(disk.getByRole("button", { name: "Delete Disk almost full" })).toBeInTheDocument();

    const memory = within(screen.getByRole("row", { name: /Memory on production/ }));
    expect(memory.getByText("Memory used above 90% for 10 min")).toBeInTheDocument();
    expect(memory.getByText("production")).toBeInTheDocument();
    expect(memory.getByText("Warning")).toBeInTheDocument();
    expect(memory.getByText("Firing on 1 server")).toBeInTheDocument();
    expect(memory.getByRole("switch", { name: "Enabled" })).not.toBeChecked();

    const down = within(screen.getByRole("row", { name: /web-1 down/ }));
    expect(down.getByText("Unreachable for 5 min")).toBeInTheDocument();
    expect(down.getByText("web-1")).toBeInTheDocument();
    expect(down.getByText("Firing on 0 servers")).toBeInTheDocument();
  });

  it("switches a rule off and reloads", async () => {
    mockApi();
    render(<AlertRulesPage />);
    const user = userEvent.setup();

    const disk = within(await screen.findByRole("row", { name: /Disk almost full/ }));
    await user.click(disk.getByRole("switch", { name: "Enabled" }));

    expect(apiFetch).toHaveBeenCalledWith("/alert-rules/r-disk", { method: "PATCH", body: { enabled: false } });
    await waitFor(() => expect(listCalls()).toBe(2));
  });

  it("switches a rule on", async () => {
    mockApi();
    render(<AlertRulesPage />);
    const user = userEvent.setup();

    const memory = within(await screen.findByRole("row", { name: /Memory on production/ }));
    await user.click(memory.getByRole("switch", { name: "Enabled" }));

    expect(apiFetch).toHaveBeenCalledWith("/alert-rules/r-memory", { method: "PATCH", body: { enabled: true } });
  });

  it("shows a refused switch", async () => {
    mockApi();
    render(<AlertRulesPage />);
    const user = userEvent.setup();
    const disk = within(await screen.findByRole("row", { name: /Disk almost full/ }));
    vi.mocked(apiFetch).mockRejectedValueOnce(new ApiError(403, "forbidden"));

    await user.click(disk.getByRole("switch", { name: "Enabled" }));

    expect(await screen.findByText("You do not have the rights to do this.")).toBeInTheDocument();
  });

  it("opens the rule dialog from New rule and from Edit", async () => {
    mockApi();
    render(<AlertRulesPage />);
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "New rule" }));
    expect(within(screen.getByRole("dialog")).getByRole("heading", { name: "New alert rule" })).toBeInTheDocument();
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "Edit Disk almost full" }));
    expect(
      within(screen.getByRole("dialog")).getByRole("heading", { name: "Edit Disk almost full" }),
    ).toBeInTheDocument();
  });

  it("names the rule and says its firing alerts end before deleting it, then reloads", async () => {
    mockApi();
    render(<AlertRulesPage />);
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Delete Disk almost full" }));
    const dialog = within(screen.getByRole("dialog"));
    expect(dialog.getByRole("heading", { name: "Delete Disk almost full?" })).toBeInTheDocument();
    expect(dialog.getByText("Its alerts that are firing now end.")).toBeInTheDocument();
    expect(apiFetch).not.toHaveBeenCalledWith("/alert-rules/r-disk", { method: "DELETE" });
    await user.click(dialog.getByRole("button", { name: "Delete rule" }));

    expect(apiFetch).toHaveBeenCalledWith("/alert-rules/r-disk", { method: "DELETE" });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(listCalls()).toBe(2);
  });

  it("shows a refused deletion in the dialog", async () => {
    mockApi();
    render(<AlertRulesPage />);
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Delete Disk almost full" }));
    vi.mocked(apiFetch).mockRejectedValueOnce(new ApiError(403, "forbidden"));
    await user.click(screen.getByRole("button", { name: "Delete rule" }));

    expect(
      await within(screen.getByRole("dialog")).findByText("You do not have the rights to do this."),
    ).toBeInTheDocument();
  });

  it("says when no rule watches anything", async () => {
    mockApi([]);
    render(<AlertRulesPage />);

    expect(await screen.findByText("No alert rules. Nothing is watched.")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("shows a failed load", async () => {
    vi.mocked(apiFetch).mockRejectedValue(new ApiError(403, "forbidden"));
    render(<AlertRulesPage />);

    expect(await screen.findByText("You do not have the rights to do this.")).toBeInTheDocument();
  });
});
