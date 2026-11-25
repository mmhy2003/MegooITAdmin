import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useRouter, useSearchParams } from "next/navigation";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ServersPage } from "@/components/servers/servers-page";
import type { ServerGroup } from "@/lib/access";
import { apiFetch } from "@/lib/api";
import type { Server } from "@/lib/servers";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), apiFetch: vi.fn() }));
vi.mock("@/lib/auth/navigate");

function group(id: string, name: string, canManage: boolean): ServerGroup {
  return {
    id,
    name,
    description: null,
    created_at: "2026-11-01T00:00:00Z",
    member_count: 1,
    server_count: 1,
    can_manage: canManage,
  };
}

const STAGING = group("g-staging", "staging", true);
const PRODUCTION = group("g-production", "production", false);

function server(id: string, name: string, g: ServerGroup, extra: Partial<Server> = {}): Server {
  return {
    id,
    name,
    address: "10.0.0.5",
    port: 22,
    os: "linux",
    role: null,
    tags: [],
    group_id: g.id,
    group_name: g.name,
    connection_settings: { username: "megoo" },
    host_key: null,
    created_at: "2026-11-01T00:00:00Z",
    updated_at: "2026-11-01T00:00:00Z",
    can_manage: g.can_manage,
    host_key_state: "not_pinned",
    host_key_fingerprint: null,
    host_key_type: null,
    host_key_pinned_at: null,
    host_key_changed_at: null,
    host_key_offered: null,
    can_connect: true,
    metrics_interval_seconds: 5,
    monitoring: null,
    ...extra,
  };
}

const DB = server("s-1", "db-01", STAGING, { address: "db.example.com", port: 2222, role: "database", tags: ["db", "web"] });
const APP = server("s-2", "app-01", PRODUCTION, { os: "windows", port: 3389, tags: ["web"] });

let replace: ReturnType<typeof vi.fn>;

function mockApi({ groups = [STAGING, PRODUCTION], servers = [DB, APP], tags = ["db", "web"] } = {}) {
  vi.mocked(apiFetch).mockImplementation(async (path: string, init?: { method?: string }) => {
    if (path === "/servers" && init?.method === "POST") return { ...DB, id: "s-3", name: "db-02" };
    if (path === "/server-groups") return groups;
    if (path === "/server-tags") return tags;
    if (path.startsWith("/servers")) return servers;
    throw new Error(`unexpected ${path}`);
  });
}

function query(search: string) {
  vi.mocked(useSearchParams).mockReturnValue(
    new URLSearchParams(search) as unknown as ReturnType<typeof useSearchParams>,
  );
}

function listCalls() {
  return vi.mocked(apiFetch).mock.calls.filter(([path, init]) => path.startsWith("/servers") && !init);
}

beforeEach(() => {
  vi.mocked(apiFetch).mockReset();
  replace = vi.fn();
  vi.mocked(useRouter).mockReturnValue({ push: vi.fn(), replace, refresh: vi.fn() } as unknown as ReturnType<
    typeof useRouter
  >);
  query("");
});

describe("ServersPage", () => {
  it("lists each server with its address, group, operating system, role and tags", async () => {
    mockApi();
    render(<ServersPage />);

    expect(await screen.findByRole("heading", { name: "Servers" })).toBeInTheDocument();
    const headers = screen.getAllByRole("columnheader").map((h) => h.textContent);
    expect(headers.slice(0, 6)).toEqual(["Name", "Address", "Group", "OS", "Role", "Tags"]);
    const db = within(await screen.findByRole("row", { name: /db-01/ }));
    expect(db.getByRole("link", { name: "db-01" })).toHaveAttribute("href", "/servers/s-1");
    expect(db.getByText("db.example.com:2222")).toBeInTheDocument();
    expect(db.getAllByRole("cell").map((c) => c.textContent).slice(2, 6)).toEqual([
      "staging",
      "Linux",
      "database",
      "dbweb",
    ]);
    const app = within(screen.getByRole("row", { name: /app-01/ }));
    expect(app.getAllByRole("cell").map((c) => c.textContent).slice(1, 4)).toEqual([
      "10.0.0.5:3389",
      "production",
      "Windows",
    ]);
  });

  it("flags the servers whose host key changed or is not pinned", async () => {
    mockApi({
      servers: [
        server("s-1", "changed-01", STAGING, { host_key_state: "changed" }),
        server("s-2", "unpinned-01", STAGING, { host_key_state: "not_pinned" }),
        server("s-3", "pinned-01", STAGING, { host_key_state: "pinned" }),
        server("s-4", "win-01", STAGING, { os: "windows", port: 3389, host_key_state: "none" }),
      ],
    });
    render(<ServersPage />);

    const nameCell = async (name: string) =>
      within(within(await screen.findByRole("row", { name: new RegExp(`^${name}`) })).getAllByRole("cell")[0]);
    expect((await nameCell("changed-01")).getByText("Host key changed")).toBeInTheDocument();
    expect((await nameCell("changed-01")).queryByText("Host key not pinned")).not.toBeInTheDocument();
    expect((await nameCell("unpinned-01")).getByText("Host key not pinned")).toBeInTheDocument();
    expect((await nameCell("unpinned-01")).queryByText("Host key changed")).not.toBeInTheDocument();
    expect((await nameCell("pinned-01")).queryByText(/Host key/)).not.toBeInTheDocument();
    expect((await nameCell("win-01")).queryByText(/Host key/)).not.toBeInTheDocument();
  });

  it("offers the row menu only on the servers the person manages", async () => {
    mockApi();
    render(<ServersPage />);
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Actions for db-01" }));
    const items = (await screen.findAllByRole("menuitem")).map((item) => item.textContent);
    expect(items).toEqual(["Edit", "Remove"]);
    expect(screen.queryByRole("button", { name: "Actions for app-01" })).not.toBeInTheDocument();
  });

  it("has no Register server button when the person manages no group", async () => {
    mockApi({ groups: [PRODUCTION], servers: [APP] });
    render(<ServersPage />);

    expect(await screen.findByRole("row", { name: /app-01/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Register server" })).not.toBeInTheDocument();
  });

  it("says so when the person sees no server group", async () => {
    mockApi({ groups: [], servers: [], tags: [] });
    render(<ServersPage />);

    expect(
      await screen.findByText(
        "You do not see any server group yet. Ask the Owner of this installation for a role.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("invites to register the first server when there is none and the person manages a group", async () => {
    mockApi({ servers: [], tags: [] });
    render(<ServersPage />);

    expect(await screen.findByText("No servers yet.")).toBeInTheDocument();
    expect(screen.getByText("Register the first one with Register server.")).toBeInTheDocument();
  });

  it("says nobody registered a server yet when the person cannot manage one", async () => {
    mockApi({ groups: [PRODUCTION], servers: [], tags: [] });
    render(<ServersPage />);

    expect(await screen.findByText("No servers yet.")).toBeInTheDocument();
    expect(screen.getByText("Nobody has registered a server in your groups yet.")).toBeInTheDocument();
  });

  it("offers to clear the filters when they match nothing", async () => {
    query("tag=nothing");
    mockApi({ servers: [] });
    render(<ServersPage />);
    const user = userEvent.setup();

    expect(await screen.findByText("No server matches these filters.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(replace).toHaveBeenCalledWith("/servers");
  });

  it("puts a chosen tag in the address", async () => {
    mockApi();
    render(<ServersPage />);
    const user = userEvent.setup();

    const web = await screen.findByRole("button", { name: "web" });
    expect(web).toHaveAttribute("aria-pressed", "false");
    await user.click(web);
    expect(replace).toHaveBeenCalledWith("/servers?tag=web");
  });

  it("puts a chosen group in the address", async () => {
    mockApi();
    render(<ServersPage />);
    const user = userEvent.setup();

    await user.click(await screen.findByRole("combobox", { name: "Group" }));
    await user.click(await screen.findByRole("option", { name: "staging" }));
    expect(replace).toHaveBeenCalledWith("/servers?group=g-staging");
  });

  it("lists the servers matching the filters in the address", async () => {
    query("group=g-staging&tag=web");
    mockApi();
    render(<ServersPage />);

    expect(await screen.findByRole("row", { name: /db-01/ })).toBeInTheDocument();
    expect(listCalls().map(([path]) => path)).toEqual(["/servers?group_id=g-staging&tag=web"]);
    expect(screen.getByRole("button", { name: "web" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("combobox", { name: "Group" })).toHaveTextContent("staging");
  });

  it("reloads the list after registering a server", async () => {
    mockApi();
    render(<ServersPage />);
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Register server" }));
    const dialog = within(await screen.findByRole("dialog"));
    expect(dialog.getByRole("combobox", { name: "Server group" })).toHaveTextContent("staging");
    await user.type(dialog.getByLabelText("Name"), "db-02");
    await user.type(dialog.getByLabelText("Address"), "10.0.0.6");
    await user.click(dialog.getByRole("button", { name: "Register server" }));

    expect(apiFetch).toHaveBeenCalledWith("/servers", expect.objectContaining({ method: "POST" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await waitFor(() => expect(listCalls()).toHaveLength(2));
  });
});
