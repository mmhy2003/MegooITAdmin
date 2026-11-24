import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useRouter } from "next/navigation";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { formatTime } from "@/components/profile/profile-page";
import { ServerPage } from "@/components/servers/server-page";
import { ApiError, apiFetch } from "@/lib/api";
import type { Server } from "@/lib/servers";

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

let push: ReturnType<typeof vi.fn>;

function mockApi(server: Server | ApiError) {
  vi.mocked(apiFetch).mockImplementation(async (path: string, init?: { method?: string }) => {
    if (init?.method === "DELETE") return undefined;
    if (path === "/servers/s-1") {
      if (server instanceof ApiError) throw server;
      return server;
    }
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

  it("shows a pinned host key, and None for no role and no tags", async () => {
    mockApi({ ...DB, host_key: "ssh-ed25519 AAAAC3Nza", role: null, tags: [] });
    render(<ServerPage serverId="s-1" />);

    await screen.findByRole("heading", { name: "db-01", level: 2 });
    expect(card("Connection").getByText("Host key").nextSibling).toHaveTextContent("ssh-ed25519 AAAAC3Nza");
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
});
