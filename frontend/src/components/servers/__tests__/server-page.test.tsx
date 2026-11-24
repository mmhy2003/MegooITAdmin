import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useRouter } from "next/navigation";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { formatTime } from "@/components/profile/profile-page";
import { ServerPage } from "@/components/servers/server-page";
import { ApiError, apiFetch } from "@/lib/api";
import type { ConnectionTestResult, Server } from "@/lib/servers";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), apiFetch: vi.fn() }));
vi.mock("@/lib/auth/navigate");

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

let push: ReturnType<typeof vi.fn>;

function mockApi(server: Server | ApiError, test: ConnectionTestResult | ApiError = WORKS) {
  vi.mocked(apiFetch).mockImplementation(async (path: string, init?: { method?: string }) => {
    if (init?.method === "DELETE") return undefined;
    if (path === "/servers/s-1") {
      if (server instanceof ApiError) throw server;
      return server;
    }
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

beforeEach(() => {
  vi.mocked(apiFetch).mockReset();
  push = vi.fn();
  vi.mocked(useRouter).mockReturnValue({ push, replace: vi.fn(), refresh: vi.fn() } as unknown as ReturnType<
    typeof useRouter
  >);
});

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
    expect(screen.getByText(/create the account deploy/)).toBeInTheDocument();
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
});
