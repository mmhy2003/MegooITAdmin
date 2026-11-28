import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AllowlistDialog } from "@/components/settings/allowlist-dialog";
import { ApiError, apiFetch } from "@/lib/api";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), apiFetch: vi.fn() }));
vi.mock("@/lib/auth/navigate");

const GROUP = { id: "g1", name: "staging" };
const NGINX = { id: "p1", pattern: "/var/log/nginx/*.log", created_at: "2026-11-01T00:00:00Z" };
const SYSLOG = { id: "p2", pattern: "/var/log/syslog", created_at: "2026-11-01T00:00:00Z" };

beforeEach(() => {
  vi.mocked(apiFetch).mockReset();
});

function mockApi({ canManage = true, add }: { canManage?: boolean; add?: () => unknown } = {}) {
  vi.mocked(apiFetch).mockImplementation(async (path: string, init?: { method?: string }) => {
    if (path === "/server-groups/g1/log-allowlist" && !init) return { can_manage: canManage, patterns: [NGINX, SYSLOG] };
    if (path === "/server-groups/g1/log-allowlist" && init?.method === "POST") return add ? add() : NGINX;
    if (path.startsWith("/server-groups/g1/log-allowlist/") && init?.method === "DELETE") return undefined;
    throw new Error(`unexpected ${path}`);
  });
}

function listCalls() {
  return vi.mocked(apiFetch).mock.calls.filter(([path, init]) => path === "/server-groups/g1/log-allowlist" && !init)
    .length;
}

function renderDialog() {
  render(<AllowlistDialog group={GROUP} open onOpenChange={vi.fn()} />);
  return userEvent.setup();
}

describe("AllowlistDialog", () => {
  it("lists the group's patterns and says a wildcard stays inside one path segment", async () => {
    mockApi();
    renderDialog();

    expect(screen.getByRole("heading", { name: "Log file patterns of staging" })).toBeInTheDocument();
    const list = within(await screen.findByRole("list", { name: "Patterns" }));
    expect(list.getAllByRole("listitem").map((i) => i.textContent)).toEqual([
      expect.stringContaining("/var/log/nginx/*.log"),
      expect.stringContaining("/var/log/syslog"),
    ]);
    expect(screen.getByText(/A wildcard stays inside one path segment/)).toBeInTheDocument();
    expect(apiFetch).toHaveBeenCalledWith("/server-groups/g1/log-allowlist");
  });

  it("removes a pattern and reloads", async () => {
    mockApi();
    const user = renderDialog();

    await user.click(await screen.findByRole("button", { name: "Remove /var/log/syslog" }));

    expect(apiFetch).toHaveBeenCalledWith("/server-groups/g1/log-allowlist/p2", { method: "DELETE" });
    await waitFor(() => expect(listCalls()).toBe(2));
  });

  it("refuses a pattern that breaks the rules without asking the server", async () => {
    mockApi();
    const user = renderDialog();

    await user.type(await screen.findByRole("textbox", { name: "Pattern" }), "/*");
    await user.click(screen.getByRole("button", { name: "Add" }));

    expect(screen.getByText("Not a valid pattern")).toBeInTheDocument();
    expect(vi.mocked(apiFetch).mock.calls.filter(([, init]) => init)).toEqual([]);
  });

  it("adds a valid pattern and reloads", async () => {
    mockApi();
    const user = renderDialog();

    const input = await screen.findByRole("textbox", { name: "Pattern" });
    await user.type(input, "/opt/app/logs/*.log");
    await user.click(screen.getByRole("button", { name: "Add" }));

    expect(apiFetch).toHaveBeenCalledWith("/server-groups/g1/log-allowlist", {
      method: "POST",
      body: { pattern: "/opt/app/logs/*.log" },
    });
    await waitFor(() => expect(listCalls()).toBe(2));
    expect(input).toHaveValue("");
  });

  it.each([
    ["pattern_exists", "This pattern is in the list already."],
    ["too_many_patterns", "This group has 50 patterns, the most allowed. Remove one first."],
  ])("says why the server refused with %s", async (detail, text) => {
    mockApi({
      add: () => {
        throw new ApiError(409, detail);
      },
    });
    const user = renderDialog();

    await user.type(await screen.findByRole("textbox", { name: "Pattern" }), "/var/log/syslog");
    await user.click(screen.getByRole("button", { name: "Add" }));

    expect(await screen.findByText(text)).toBeInTheDocument();
  });

  it("shows the patterns only to someone who cannot manage the group", async () => {
    mockApi({ canManage: false });
    renderDialog();

    expect(await screen.findByText("/var/log/syslog")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Remove/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "Pattern" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add" })).not.toBeInTheDocument();
  });
});
