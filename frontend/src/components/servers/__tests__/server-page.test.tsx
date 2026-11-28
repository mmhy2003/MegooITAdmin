import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useRouter, useSearchParams } from "next/navigation";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { formatTime } from "@/components/profile/profile-page";
import { ServerPage } from "@/components/servers/server-page";
import { useRefresh } from "@/hooks/use-refresh";
import type { Alert } from "@/lib/alerts";
import { ApiError, apiFetch } from "@/lib/api";
import type { ChecksResponse, Container } from "@/lib/checks";
import type { ConnectionTestResult, Server } from "@/lib/servers";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), apiFetch: vi.fn() }));
vi.mock("@/lib/auth/navigate");
vi.mock("@/hooks/use-refresh", () => ({ useRefresh: vi.fn() }));
vi.mock("@/components/servers/performance/live-strip", () => ({ LiveStrip: () => <div>live strip</div> }));
vi.mock("next/dynamic", () => ({
  default: () =>
    function PerformanceTab(p: { range: string; onRange: (range: string) => void }) {
      return (
        <div>
          performance tab {p.range}
          <button type="button" onClick={() => p.onRange("7d")}>
            pick 7 days
          </button>
          <button type="button" onClick={() => p.onRange("live")}>
            pick live
          </button>
        </div>
      );
    },
}));

const DB: Server = {
  id: "s-1",
  name: "db-01",
  address: "db.example.com",
  port: 2222,
  os: "linux",
  role: "database",
  tags: ["db", "web"],
  group_id: "g-staging",
  group_name: "staging",
  connection_settings: { username: "deploy" },
  host_key: null,
  created_at: "2026-11-01T08:00:00Z",
  updated_at: "2026-11-02T09:30:00Z",
  can_manage: true,
  host_key_state: "not_pinned",
  host_key_fingerprint: null,
  host_key_type: null,
  host_key_pinned_at: null,
  host_key_changed_at: null,
  host_key_offered: null,
  can_connect: true,
  can_view_logs: false,
  metrics_interval_seconds: 5,
  monitoring: null,
};

const FINGERPRINT = "SHA256:abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG";
const PINNED: Server = {
  ...DB,
  host_key_state: "pinned",
  host_key_fingerprint: FINGERPRINT,
  host_key_type: "ssh-ed25519",
  host_key_pinned_at: "2026-11-03T10:00:00Z",
};
const CHANGED: Server = {
  ...PINNED,
  host_key_state: "changed",
  host_key_changed_at: "2026-11-04T11:00:00Z",
  host_key_offered: { fingerprint: "SHA256:newkey", type: "ssh-ed25519", at: "2026-11-04T11:00:00Z" },
};
const WORKS: ConnectionTestResult = {
  ok: true,
  reason: null,
  checks: [
    { name: "host_key", status: "passed" },
    { name: "platform_key", status: "passed" },
    { name: "not_root", status: "passed" },
    { name: "not_in_docker_group", status: "passed" },
    { name: "in_log_groups", status: "passed" },
    { name: "sudo_checker", status: "passed" },
    { name: "sudo_limited", status: "passed" },
  ],
};

const AT = "2026-11-25T11:59:30Z";

/** The six checks of a Linux server: one failed unit, the others with small results. */
const CHECKS: ChecksResponse = {
  can_view_processes: true,
  checks: [
    {
      kind: "services",
      status: "ok",
      checked_at: AT,
      every_seconds: 60,
      data: {
        total: 42,
        running: 41,
        failed: 1,
        failed_units: [{ unit: "nginx.service", description: "A high performance web server" }],
      },
      data_at: AT,
    },
    {
      kind: "updates",
      status: "ok",
      checked_at: AT,
      every_seconds: 3600,
      data: { manager: "apt", pending: 3, security: 1, reboot_required: false, lists_refreshed_at: AT },
      data_at: AT,
    },
    {
      kind: "logins",
      status: "ok",
      checked_at: AT,
      every_seconds: 300,
      data: { failed_24h: 0, top_sources: [] },
      data_at: AT,
    },
    {
      kind: "certificates",
      status: "ok",
      checked_at: AT,
      every_seconds: 21600,
      data: { certificates: [] },
      data_at: AT,
    },
    {
      kind: "processes",
      status: "ok",
      checked_at: AT,
      every_seconds: 30,
      data: {
        by_cpu: [{ pid: 101, name: "postgres", user: "postgres", cpu_percent: 12.5, memory_bytes: 104857600 }],
        by_memory: [{ pid: 101, name: "postgres", user: "postgres", cpu_percent: 12.5, memory_bytes: 104857600 }],
      },
      data_at: AT,
    },
    {
      kind: "containers",
      status: "ok",
      checked_at: AT,
      every_seconds: 30,
      data: { total: 4, running: 2, not_running: 2 },
      data_at: AT,
    },
  ],
};

function container(fields: Partial<Container> & Pick<Container, "container_id" | "name" | "image" | "state">): Container {
  return {
    runtime: "docker",
    compose_project: null,
    compose_service: null,
    status: "Up 3 days",
    first_seen_at: "2026-11-22T10:00:00Z",
    last_seen_at: AT,
    ...fields,
  };
}

/** The four containers of the fake server. */
const CONTAINERS: Container[] = [
  container({ container_id: "1".repeat(64), name: "shop-web-1", image: "nginx:1.27", compose_project: "shop", state: "running" }),
  container({ container_id: "2".repeat(64), name: "shop-db-1", image: "postgres:17", compose_project: "shop", state: "running" }),
  container({
    container_id: "3".repeat(64),
    name: "monitoring-grafana-1",
    image: "grafana/grafana:11.3.0",
    compose_project: "monitoring",
    state: "exited",
  }),
  container({ container_id: "4".repeat(64), name: "hello-adhoc", image: "busybox:1.37", state: "restarting" }),
];

function alertOf(id: string, fields: Partial<Alert> = {}): Alert {
  return {
    id,
    server_id: "s-1",
    server_name: "db-01",
    group_id: "g-staging",
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

/** Two alerts firing on the fake server, then one that resolved. */
const ALERTS: Alert[] = [
  alertOf("a-1"),
  alertOf("a-2", { metric: "mem.used_percent", severity: "warning", instance: "", value: 91.5 }),
  alertOf("a-3", { state: "resolved", fired_at: "2026-11-26T08:00:00Z", resolved_at: "2026-11-26T08:30:00Z" }),
];

let push: ReturnType<typeof vi.fn>;
let replace: ReturnType<typeof vi.fn>;

function mockApi(
  server: Server | ApiError,
  test: ConnectionTestResult | ApiError = WORKS,
  checks: ChecksResponse | ApiError = CHECKS,
  alerts: Alert[] = [],
) {
  vi.mocked(apiFetch).mockImplementation(async (path: string, init?: { method?: string }) => {
    if (init?.method === "DELETE") return undefined;
    if (path === "/servers/s-1") {
      if (server instanceof ApiError) throw server;
      return server;
    }
    if (path === "/servers/s-1/checks") {
      if (checks instanceof ApiError) throw checks;
      return checks;
    }
    if (path === "/servers/s-1/containers") return CONTAINERS;
    if (path === "/servers/s-1/alerts") return alerts;
    if (path === "/servers/s-1/connection-test") {
      if (test instanceof ApiError) throw test;
      return test;
    }
    if (path === "/servers/s-1/host-key/fetch") return new Promise(() => {});
    if (path === "/ssh/public-key") return { public_key: "ssh-ed25519 AAAAplatform megooitadmin" };
    if (path === "/server-groups") return [];
    if (path === "/server-tags") return [];
    throw new Error(`unexpected ${path}`);
  });
}

function card(title: string) {
  return within(screen.getByRole("heading", { name: title }).closest("[data-slot=card]") as HTMLElement);
}

function refreshArgs() {
  return vi.mocked(useRefresh).mock.lastCall!;
}

async function refreshNow() {
  await act(async () => {
    refreshArgs()[0]();
  });
}

beforeEach(() => {
  vi.mocked(apiFetch).mockReset();
  vi.mocked(useRefresh).mockReset();
  push = vi.fn();
  replace = vi.fn();
  vi.mocked(useRouter).mockReturnValue({ push, replace, refresh: vi.fn() } as unknown as ReturnType<typeof useRouter>);
  setTab(null);
});

function setTab(tab: string | null, range?: string) {
  vi.mocked(useSearchParams).mockReturnValue(
    new URLSearchParams({ ...(tab ? { tab } : {}), ...(range ? { range } : {}) }) as unknown as ReturnType<
      typeof useSearchParams
    >,
  );
}

const CARDS = ["Services", "Updates", "Failed sign-ins", "Certificates", "Top processes", "Containers"];

function checkReads() {
  return vi
    .mocked(apiFetch)
    .mock.calls.filter(([path]) => ["/servers/s-1/checks", "/servers/s-1/containers", "/servers/s-1/alerts"].includes(path));
}

describe("ServerPage", () => {
  it("shows the server's name, badges, Overview tab and its Connection and Details cards", async () => {
    mockApi(DB);
    render(<ServerPage serverId="s-1" />);

    expect(await screen.findByRole("heading", { name: "db-01", level: 2 })).toBeInTheDocument();
    expect(screen.getByRole("tablist", { name: "Server" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Overview" })).toHaveAttribute("aria-selected", "true");

    const connection = card("Connection");
    expect(connection.getByText("Address").nextSibling).toHaveTextContent("db.example.com");
    expect(connection.getByText("Port").nextSibling).toHaveTextContent("2222");
    expect(connection.getByText("Login account").nextSibling).toHaveTextContent("deploy");
    expect(connection.getByText("Host key").nextSibling).toHaveTextContent("Not pinned yet");

    const details = card("Details");
    expect(details.getByText("Server group").nextSibling).toHaveTextContent("staging");
    expect(details.getByText("Operating system").nextSibling).toHaveTextContent("Linux");
    expect(details.getByText("Role").nextSibling).toHaveTextContent("database");
    expect(details.getByText("Tags").nextSibling).toHaveTextContent("dbweb");
    expect(details.getByText("Registered").nextSibling).toHaveTextContent(formatTime(DB.created_at));
    expect(details.getByText("Last changed").nextSibling).toHaveTextContent(formatTime(DB.updated_at));
    expect(vi.mocked(apiFetch)).toHaveBeenCalledWith("/servers/s-1");
  });

  it("shows a pinned host key's fingerprint, type and time, and None for no role and no tags", async () => {
    mockApi({ ...PINNED, role: null, tags: [] });
    render(<ServerPage serverId="s-1" />);

    await screen.findByRole("heading", { name: "db-01", level: 2 });
    const hostKey = card("Connection").getByText("Host key").nextSibling as HTMLElement;
    expect(within(hostKey).getByText(FINGERPRINT)).toHaveClass("font-mono");
    expect(hostKey).toHaveTextContent("ssh-ed25519");
    expect(hostKey).toHaveTextContent(`Pinned ${formatTime(PINNED.host_key_pinned_at!)}`);
    const details = card("Details");
    expect(details.getByText("Role").nextSibling).toHaveTextContent("None");
    expect(details.getByText("Tags").nextSibling).toHaveTextContent("None");
  });

  it("offers Edit and Remove only when the person manages the server", async () => {
    mockApi({ ...DB, can_manage: false });
    render(<ServerPage serverId="s-1" />);

    await screen.findByRole("heading", { name: "db-01", level: 2 });
    expect(screen.queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Remove" })).not.toBeInTheDocument();
  });

  it("says the server does not exist or cannot be seen on a 404", async () => {
    mockApi(new ApiError(404, "not_found"));
    render(<ServerPage serverId="s-1" />);

    expect(await screen.findByText("This server does not exist, or you cannot see it.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to servers" })).toHaveAttribute("href", "/servers");
  });

  it("goes back to the servers list after removing the server", async () => {
    mockApi(DB);
    render(<ServerPage serverId="s-1" />);
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Remove" }));
    await user.click(await screen.findByRole("button", { name: "Remove server" }));

    await waitFor(() => expect(push).toHaveBeenCalledWith("/servers"));
    expect(vi.mocked(apiFetch)).toHaveBeenCalledWith("/servers/s-1", { method: "DELETE" });
  });

  it.each([
    {
      server: DB,
      badge: "Host key not pinned",
      banner: "The host key of db-01 is not pinned yet. Nothing connects to it until it is.",
      button: "Pin host key",
      testable: false,
    },
    { server: PINNED, badge: "Host key pinned", banner: null, button: null, testable: true },
    {
      server: CHANGED,
      badge: "Host key changed",
      banner: "Host key changed: connections to db-01 are blocked",
      button: "Review host key",
      testable: false,
    },
  ])("shows a manager the $badge badge, banner and buttons", async ({ server, badge, banner, button, testable }) => {
    mockApi(server);
    render(<ServerPage serverId="s-1" />);

    await screen.findByRole("heading", { name: "db-01", level: 2 });
    expect(screen.getByText(badge)).toHaveAttribute("data-slot", "badge");
    for (const other of ["Host key not pinned", "Host key pinned", "Host key changed"].filter((b) => b !== badge)) {
      expect(screen.queryByText(other)).not.toBeInTheDocument();
    }
    if (banner) expect(screen.getByText(banner)).toBeInTheDocument();
    for (const name of ["Pin host key", "Review host key"]) {
      if (name === button) expect(screen.getByRole("button", { name })).toBeEnabled();
      else expect(screen.queryByRole("button", { name })).not.toBeInTheDocument();
    }
    const test = screen.getByRole("button", { name: "Test connection" });
    if (testable) expect(test).toBeEnabled();
    else expect(test).toBeDisabled();
    expect(await screen.findByRole("heading", { name: "Platform access" })).toBeInTheDocument();
    expect(await screen.findByText(/--user 'deploy'$/)).toBeInTheDocument();
  });

  it("tells when a changed key was seen, and that the new key could not be read", async () => {
    mockApi({ ...CHANGED, host_key_offered: null });
    render(<ServerPage serverId="s-1" />);

    await screen.findByRole("heading", { name: "db-01", level: 2 });
    expect(
      screen.getByText(
        `On ${formatTime(CHANGED.host_key_changed_at!)} the server presented another host key than the pinned one. ` +
          "The server may have been reinstalled, or someone may be in the way.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("The new key could not be read.")).toBeInTheDocument();
  });

  it("lets an Operator test the connection but asks an Admin to pin or review the key", async () => {
    mockApi({ ...DB, can_manage: false });
    const { unmount } = render(<ServerPage serverId="s-1" />);

    await screen.findByRole("heading", { name: "db-01", level: 2 });
    expect(screen.getByRole("button", { name: "Test connection" })).toBeInTheDocument();
    expect(screen.getByText("Ask an Admin of staging to pin it.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Pin host key" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Platform access" })).not.toBeInTheDocument();
    unmount();

    mockApi({ ...CHANGED, can_manage: false });
    render(<ServerPage serverId="s-1" />);
    await screen.findByRole("heading", { name: "db-01", level: 2 });
    expect(screen.getByText("An Admin of staging must review it.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Review host key" })).not.toBeInTheDocument();
  });

  it("offers no Test connection to someone who cannot connect", async () => {
    mockApi({ ...PINNED, can_manage: false, can_connect: false });
    render(<ServerPage serverId="s-1" />);

    await screen.findByRole("heading", { name: "db-01", level: 2 });
    expect(screen.getByText("Host key pinned")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Test connection" })).not.toBeInTheDocument();
  });

  it("shows no host key state, banner, test or access card for a Windows server", async () => {
    mockApi({ ...DB, os: "windows", port: 3389, host_key_state: "none" });
    render(<ServerPage serverId="s-1" />);

    await screen.findByRole("heading", { name: "db-01", level: 2 });
    expect(screen.queryByText(/^Host key (pinned|not pinned|changed)$/)).not.toBeInTheDocument();
    expect(screen.queryByText(/is not pinned yet/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Test connection" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Pin host key" })).not.toBeInTheDocument();
    expect(card("Connection").queryByText("Host key")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Platform access" })).not.toBeInTheDocument();
  });

  it("tests the connection, shows the result and reloads the server", async () => {
    mockApi({ ...PINNED, can_manage: false });
    render(<ServerPage serverId="s-1" />);
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Test connection" }));

    expect(await screen.findByText("Connection works")).toBeInTheDocument();
    expect(screen.getAllByText("Passed")).toHaveLength(7);
    expect(vi.mocked(apiFetch)).toHaveBeenCalledWith("/servers/s-1/connection-test", { method: "POST" });
    expect(vi.mocked(apiFetch).mock.calls.filter(([path]) => path === "/servers/s-1")).toHaveLength(2);
  });

  it("shows a refused test's message and reloads the server", async () => {
    mockApi({ ...PINNED, can_manage: false }, new ApiError(409, "host_key_changed"));
    render(<ServerPage serverId="s-1" />);
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Test connection" }));

    expect(
      await screen.findByText("The server's host key has changed. Review it before connecting."),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(vi.mocked(apiFetch).mock.calls.filter(([path]) => path === "/servers/s-1")).toHaveLength(2),
    );
  });

  it("opens the pin dialog, which fetches the server's key", async () => {
    mockApi(DB);
    render(<ServerPage serverId="s-1" />);
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Pin host key" }));

    expect(await screen.findByRole("dialog", { name: "Pin the host key of db-01" })).toBeInTheDocument();
    expect(vi.mocked(apiFetch)).toHaveBeenCalledWith("/servers/s-1/host-key/fetch", { method: "POST" });
  });

  it("opens the review dialog from the changed banner", async () => {
    mockApi(CHANGED);
    render(<ServerPage serverId="s-1" />);
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Review host key" }));

    expect(await screen.findByRole("dialog", { name: "Review the host key of db-01" })).toBeInTheDocument();
  });

  it("shows the monitoring badge after the name and the Monitoring card first", async () => {
    mockApi({
      ...PINNED,
      monitoring: { state: "unreachable", reason: "unreachable", since: "2026-11-05T10:00:00Z", last_sample_at: null },
    });
    render(<ServerPage serverId="s-1" />);

    const name = await screen.findByRole("heading", { name: "db-01", level: 2 });
    const titleRow = within(name.parentElement as HTMLElement);
    expect(titleRow.getByText("Unreachable")).toHaveAttribute("data-slot", "badge");
    expect(name.nextElementSibling).toHaveTextContent("Unreachable");
    const monitoring = card("Monitoring");
    expect(monitoring.getByText("The server did not answer.")).toBeInTheDocument();
    expect(monitoring.getByText("Last sample").nextSibling).toHaveTextContent("None yet");
    const order = screen
      .getByRole("heading", { name: "Monitoring" })
      .compareDocumentPosition(screen.getByRole("heading", { name: "Connection" }));
    expect(order & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("updates the state on a background re-read", async () => {
    mockApi(PINNED);
    render(<ServerPage serverId="s-1" />);
    await screen.findByRole("heading", { name: "db-01", level: 2 });
    expect(screen.queryByText("Reachable")).not.toBeInTheDocument();

    mockApi({
      ...PINNED,
      monitoring: {
        state: "reachable",
        reason: null,
        since: "2026-11-05T10:00:00Z",
        last_sample_at: "2026-11-05T10:05:00Z",
      },
    });
    await refreshNow();

    expect(screen.getAllByText("Reachable").length).toBeGreaterThan(0);
    expect(vi.mocked(apiFetch)).toHaveBeenCalledWith("/servers/s-1", { background: true });
  });

  it("shows the missing card when a background re-read answers 404", async () => {
    mockApi(PINNED);
    render(<ServerPage serverId="s-1" />);
    await screen.findByRole("heading", { name: "db-01", level: 2 });

    mockApi(new ApiError(404, "not_found"));
    await refreshNow();

    expect(screen.getByText("This server does not exist, or you cannot see it.")).toBeInTheDocument();
  });

  it("keeps the page and shows no error when a background re-read fails otherwise", async () => {
    mockApi(PINNED);
    render(<ServerPage serverId="s-1" />);
    await screen.findByRole("heading", { name: "db-01", level: 2 });

    mockApi(new ApiError(500, "invalid"));
    await refreshNow();

    expect(screen.getByRole("heading", { name: "db-01", level: 2 })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("pauses the re-read while a dialog is open or a test runs", async () => {
    mockApi(DB);
    const { unmount } = render(<ServerPage serverId="s-1" />);
    const user = userEvent.setup();

    await screen.findByRole("heading", { name: "db-01", level: 2 });
    expect(refreshArgs()[1]).toBe(true);
    await user.click(screen.getByRole("button", { name: "Remove" }));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(refreshArgs()[1]).toBe(false);
    unmount();

    mockApi(PINNED);
    const pending = vi.mocked(apiFetch).getMockImplementation()!;
    vi.mocked(apiFetch).mockImplementation((path: string, init?: { method?: string }) =>
      path === "/servers/s-1/connection-test" ? new Promise(() => {}) : pending(path, init),
    );
    render(<ServerPage serverId="s-1" />);
    await user.click(await screen.findByRole("button", { name: "Test connection" }));
    expect(await screen.findByRole("button", { name: "Testing…" })).toBeDisabled();
    expect(refreshArgs()[1]).toBe(false);
  });

  it("shows the six check cards on Overview for a Linux server", async () => {
    mockApi(PINNED);
    render(<ServerPage serverId="s-1" />);

    expect(await screen.findByRole("heading", { name: "Services" })).toBeInTheDocument();
    for (const name of CARDS) expect(screen.getByRole("heading", { name, level: 3 })).toBeInTheDocument();
    expect(card("Services").getByText("nginx.service")).toBeInTheDocument();
    expect(card("Containers").getByRole("link", { name: "Show containers" })).toHaveAttribute(
      "href",
      "/servers/s-1?tab=containers",
    );
    expect(screen.getByRole("tabpanel")).toContainElement(screen.getByRole("heading", { name: "Services" }));
    expect(vi.mocked(apiFetch)).toHaveBeenCalledWith("/servers/s-1/checks");
    expect(vi.mocked(apiFetch)).toHaveBeenCalledWith("/servers/s-1/containers");
    const order = screen
      .getByRole("heading", { name: "Monitoring" })
      .compareDocumentPosition(screen.getByRole("heading", { name: "Services" }));
    expect(order & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    const after = screen
      .getByRole("heading", { name: "Services" })
      .compareDocumentPosition(screen.getByRole("heading", { name: "Connection" }));
    expect(after & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("reads no checks or containers and offers no Containers tab for a Windows server", async () => {
    setTab("containers");
    mockApi({ ...DB, os: "windows", port: 3389, host_key_state: "none" });
    render(<ServerPage serverId="s-1" />);

    await screen.findByRole("heading", { name: "db-01", level: 2 });
    await refreshNow();
    expect(screen.getAllByRole("tab").map((tab) => tab.textContent)).toEqual(["Overview"]);
    expect(screen.getByRole("tab", { name: "Overview" })).toHaveAttribute("aria-selected", "true");
    for (const name of CARDS) expect(screen.queryByRole("heading", { name })).not.toBeInTheDocument();
    expect(card("Connection").getByText("Address")).toBeInTheDocument();
    expect(checkReads()).toHaveLength(0);
  });

  it("shows the containers grouped by Compose project on the Containers tab", async () => {
    setTab("containers");
    mockApi(PINNED);
    render(<ServerPage serverId="s-1" />);

    const tab = await screen.findByRole("tab", { name: "Containers (4)" });
    expect(tab).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "Overview" })).toHaveAttribute("aria-selected", "false");
    const panel = within(screen.getByRole("tabpanel"));
    for (const name of ["monitoring", "shop", "No Compose project"]) {
      expect(panel.getByRole("heading", { name, level: 3 })).toBeInTheDocument();
    }
    for (const name of CARDS.filter((n) => n !== "Containers")) {
      expect(screen.queryByRole("heading", { name })).not.toBeInTheDocument();
    }
    expect(screen.queryByRole("heading", { name: "Connection" })).not.toBeInTheDocument();
    expect(tab).toHaveAttribute("aria-controls", screen.getByRole("tabpanel").id);
  });

  it("switches tabs by replacing the address without scrolling", async () => {
    mockApi(PINNED);
    render(<ServerPage serverId="s-1" />);
    const user = userEvent.setup();

    await user.click(await screen.findByRole("tab", { name: "Containers (4)" }));
    expect(replace).toHaveBeenLastCalledWith("/servers/s-1?tab=containers", { scroll: false });
    await user.click(screen.getByRole("tab", { name: "Overview" }));
    expect(replace).toHaveBeenLastCalledWith("/servers/s-1", { scroll: false });
  });

  it("offers a Linux server Overview, Performance, Containers and Alerts tabs in that order", async () => {
    mockApi(PINNED);
    render(<ServerPage serverId="s-1" />);

    await screen.findByRole("tab", { name: "Containers (4)" });
    expect(screen.getAllByRole("tab").map((tab) => tab.textContent)).toEqual([
      "Overview",
      "Performance",
      "Containers (4)",
      "Alerts",
    ]);
    expect(screen.getByRole("tab", { name: "Performance" })).toHaveAttribute("aria-selected", "false");
    expect(screen.queryByText(/performance tab/)).not.toBeInTheDocument();
  });

  it("shows a Windows server's Overview for ?tab=performance, with no Performance tab", async () => {
    setTab("performance", "30d");
    mockApi({ ...DB, os: "windows", port: 3389, host_key_state: "none" });
    render(<ServerPage serverId="s-1" />);

    await screen.findByRole("heading", { name: "db-01", level: 2 });
    expect(screen.queryByRole("tab", { name: "Performance" })).not.toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Overview" })).toHaveAttribute("aria-selected", "true");
    expect(card("Connection").getByText("Address")).toBeInTheDocument();
    expect(screen.queryByText(/performance tab/)).not.toBeInTheDocument();
  });

  it("selects the Performance tab from the address and passes its range", async () => {
    setTab("performance", "30d");
    mockApi(PINNED);
    render(<ServerPage serverId="s-1" />);

    const tab = await screen.findByRole("tab", { name: "Performance" });
    expect(tab).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "Overview" })).toHaveAttribute("aria-selected", "false");
    const panel = screen.getByRole("tabpanel");
    expect(panel).toHaveTextContent("performance tab 30d");
    expect(panel).toHaveAttribute("aria-labelledby", "server-tab-performance");
    expect(tab).toHaveAttribute("id", "server-tab-performance");
    expect(screen.queryByRole("heading", { name: "Connection" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Services" })).not.toBeInTheDocument();
  });

  it("opens the Performance tab on Live when the range is missing or unknown", async () => {
    setTab("performance", "90d");
    mockApi(PINNED);
    render(<ServerPage serverId="s-1" />);

    expect(await screen.findByText(/performance tab/)).toHaveTextContent("performance tab live");
  });

  it("switches to the Performance tab and changes its range by replacing the address", async () => {
    mockApi(PINNED);
    render(<ServerPage serverId="s-1" />);
    const user = userEvent.setup();

    await user.click(await screen.findByRole("tab", { name: "Performance" }));
    expect(replace).toHaveBeenLastCalledWith("/servers/s-1?tab=performance", { scroll: false });

    setTab("performance");
    await user.click(screen.getByRole("tab", { name: "Overview" }));
    expect(replace).toHaveBeenLastCalledWith("/servers/s-1", { scroll: false });
  });

  it("puts a past range in the address and leaves Live out of it", async () => {
    setTab("performance", "24h");
    mockApi(PINNED);
    render(<ServerPage serverId="s-1" />);
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "pick 7 days" }));
    expect(replace).toHaveBeenLastCalledWith("/servers/s-1?tab=performance&range=7d", { scroll: false });
    await user.click(screen.getByRole("button", { name: "pick live" }));
    expect(replace).toHaveBeenLastCalledWith("/servers/s-1?tab=performance", { scroll: false });
  });

  const REACHABLE = { state: "reachable", reason: null, since: AT, last_sample_at: AT } as const;

  it.each(["reachable", "unreachable"] as const)(
    "shows the live strip before the Monitoring card for a %s Linux server",
    async (state) => {
      mockApi({ ...PINNED, monitoring: { ...REACHABLE, state } });
      render(<ServerPage serverId="s-1" />);

      const strip = await screen.findByText("live strip");
      const monitoring = screen.getByRole("heading", { name: "Monitoring" });
      expect(strip.compareDocumentPosition(monitoring) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    },
  );

  it.each([
    ["a Windows server", { ...PINNED, os: "windows", host_key_state: "none", monitoring: REACHABLE }],
    ["a server that is not monitored", { ...PINNED, monitoring: { ...REACHABLE, state: "not_monitored" } }],
    ["a server the collector has not looked at", { ...PINNED, monitoring: null }],
  ] as const)("shows no live strip for %s", async (_, server) => {
    mockApi(server as Server);
    render(<ServerPage serverId="s-1" />);

    await screen.findByRole("heading", { name: "Connection" });
    expect(screen.queryByText("live strip")).not.toBeInTheDocument();
  });

  it.each(["containers", "performance"])("shows no live strip on ?tab=%s", async (tab) => {
    setTab(tab);
    mockApi({ ...PINNED, monitoring: REACHABLE });
    render(<ServerPage serverId="s-1" />);

    await screen.findByRole("tab", { name: "Containers (4)" });
    expect(screen.getByRole("tab", { selected: true })).toHaveAttribute("id", `server-tab-${tab}`);
    expect(screen.queryByText("live strip")).not.toBeInTheDocument();
  });

  it("re-reads the checks and containers in the background and updates the cards", async () => {
    mockApi(PINNED);
    render(<ServerPage serverId="s-1" />);
    expect(await screen.findByText("1 failed")).toBeInTheDocument();

    const services = CHECKS.checks[0];
    mockApi(PINNED, WORKS, {
      ...CHECKS,
      checks: [
        {
          ...services,
          data: {
            total: 42,
            running: 40,
            failed: 2,
            failed_units: [
              { unit: "nginx.service", description: "A high performance web server" },
              { unit: "cron.service", description: "Regular background program processing daemon" },
            ],
          },
        },
        ...CHECKS.checks.slice(1),
      ],
    });
    await refreshNow();

    expect(await screen.findByText("2 failed")).toBeInTheDocument();
    expect(vi.mocked(apiFetch)).toHaveBeenCalledWith("/servers/s-1/checks", { background: true });
    expect(vi.mocked(apiFetch)).toHaveBeenCalledWith("/servers/s-1/containers", { background: true });
  });

  it("reads a Linux server's alerts with its facts, and again in the background", async () => {
    mockApi(PINNED, WORKS, CHECKS, ALERTS.slice(2));
    render(<ServerPage serverId="s-1" />);
    await screen.findByRole("heading", { name: "Services" });
    expect(vi.mocked(apiFetch)).toHaveBeenCalledWith("/servers/s-1/alerts");
    expect(screen.getByRole("tab", { name: "Alerts" })).toBeInTheDocument();
    expect(screen.queryByText(/alerts? firing/)).not.toBeInTheDocument();

    mockApi(PINNED, WORKS, CHECKS, ALERTS);
    await refreshNow();

    expect(await screen.findByRole("tab", { name: "Alerts 2" })).toBeInTheDocument();
    expect(screen.getByText("2 alerts firing")).toBeInTheDocument();
    expect(vi.mocked(apiFetch)).toHaveBeenCalledWith("/servers/s-1/alerts", { background: true });
  });

  it("names the firing alerts in a banner above the tabs, with a link to the Alerts tab", async () => {
    mockApi(PINNED, WORKS, CHECKS, ALERTS);
    render(<ServerPage serverId="s-1" />);

    const title = await screen.findByText("2 alerts firing");
    const banner = within(title.closest("[data-slot=alert]") as HTMLElement);
    expect(banner.getAllByRole("listitem").map((item) => item.textContent)).toEqual([
      "Criticaldb-01: / is 93.3% full",
      "Warningdb-01: memory is 91.5% used",
    ]);
    expect(banner.getByRole("link", { name: "Show alerts" })).toHaveAttribute("href", "/servers/s-1?tab=alerts");
    const order = title.compareDocumentPosition(screen.getByRole("tablist", { name: "Server" }));
    expect(order & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByRole("tab", { name: "Alerts 2" })).toHaveAttribute("id", "server-tab-alerts");
  });

  it("shows the firing alerts, then the history, on ?tab=alerts", async () => {
    setTab("alerts");
    mockApi(PINNED, WORKS, CHECKS, ALERTS);
    render(<ServerPage serverId="s-1" />);

    const tab = await screen.findByRole("tab", { name: "Alerts 2" });
    expect(tab).toHaveAttribute("aria-selected", "true");
    const panel = screen.getByRole("tabpanel");
    expect(panel).toHaveAttribute("aria-labelledby", "server-tab-alerts");
    const ids = (name: string) =>
      [...within(panel).getByRole("region", { name }).querySelectorAll("[data-alert-id]")].map((row) =>
        row.getAttribute("data-alert-id"),
      );
    expect(ids("Firing")).toEqual(["a-1", "a-2"]);
    expect(ids("History")).toEqual(["a-3"]);
    expect(screen.queryByRole("heading", { name: "Services" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Connection" })).not.toBeInTheDocument();
  });

  it("switches to the Alerts tab by replacing the address", async () => {
    mockApi(PINNED);
    render(<ServerPage serverId="s-1" />);
    await userEvent.setup().click(await screen.findByRole("tab", { name: "Alerts" }));
    expect(replace).toHaveBeenLastCalledWith("/servers/s-1?tab=alerts", { scroll: false });
  });

  it("reads no alerts and shows neither the banner nor the Alerts tab for a Windows server", async () => {
    setTab("alerts");
    mockApi({ ...DB, os: "windows", port: 3389, host_key_state: "none" }, WORKS, CHECKS, ALERTS);
    render(<ServerPage serverId="s-1" />);

    await screen.findByRole("heading", { name: "db-01", level: 2 });
    await refreshNow();
    expect(screen.queryByRole("tab", { name: /Alerts/ })).not.toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Overview" })).toHaveAttribute("aria-selected", "true");
    expect(screen.queryByText(/alerts? firing/)).not.toBeInTheDocument();
    expect(vi.mocked(apiFetch).mock.calls.filter(([path]) => path === "/servers/s-1/alerts")).toHaveLength(0);
  });

  it("pauses the re-read while the Edit dialog is open", async () => {
    mockApi(PINNED);
    render(<ServerPage serverId="s-1" />);
    const user = userEvent.setup();

    await screen.findByRole("heading", { name: "Services" });
    expect(refreshArgs()[1]).toBe(true);
    await user.click(screen.getByRole("button", { name: "Edit" }));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(refreshArgs()[1]).toBe(false);
  });

  it("shows an error when the checks cannot be read", async () => {
    mockApi(PINNED, WORKS, new ApiError(500, "invalid"));
    render(<ServerPage serverId="s-1" />);

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "db-01", level: 2 })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Services" })).not.toBeInTheDocument();
  });

  it("shows no error when a background read of the checks fails", async () => {
    mockApi(PINNED);
    render(<ServerPage serverId="s-1" />);
    await screen.findByRole("heading", { name: "Services" });

    mockApi(PINNED, WORKS, new ApiError(500, "invalid"));
    await refreshNow();

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Services" })).toBeInTheDocument();
  });
});
