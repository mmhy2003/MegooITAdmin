import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { GroupsPage } from "@/components/settings/groups-page";
import { apiFetch } from "@/lib/api";
import { type ServerGroup, switchesFor, type UserRow } from "@/lib/access";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), apiFetch: vi.fn() }));
vi.mock("@/lib/auth/navigate");

const PRODUCTION: ServerGroup = {
  id: "g-production",
  name: "production",
  description: "Live servers",
  created_at: "2026-11-01T00:00:00Z",
  member_count: 0,
  server_count: 0,
  can_manage: true,
};
const STAGING: ServerGroup = {
  id: "g-staging",
  name: "staging",
  description: null,
  created_at: "2026-11-01T00:00:00Z",
  member_count: 2,
  server_count: 0,
  can_manage: true,
};

function person(id: string, name: string, groups: string[]): UserRow {
  return {
    id,
    name,
    email: `${id}@example.com`,
    platform_role: null,
    status: "active",
    mfa_enrolled: true,
    invite_expires_at: null,
    grants: groups.map((g) => ({ group_id: g, group_name: g, role: "admin", ...switchesFor("admin") })),
  };
}

const USERS: UserRow[] = [
  person("u-ada", "Ada Admin", ["g-staging"]),
  person("u-otto", "Otto Operator", ["g-production", "g-staging"]),
  { ...person("u-olive", "Olive Owner", []), platform_role: "owner" },
];

beforeEach(() => {
  vi.mocked(apiFetch).mockReset();
});

function mockApi() {
  vi.mocked(apiFetch).mockImplementation(async (path: string, init?: { method?: string }) => {
    if (path === "/server-groups" && init?.method === "POST") return STAGING;
    if (path.startsWith("/server-groups/") && init?.method === "PATCH") return STAGING;
    if (path.startsWith("/server-groups/") && init?.method === "DELETE") return undefined;
    if (path === "/server-groups") return [PRODUCTION, STAGING];
    if (path === "/users") return USERS;
    throw new Error(`unexpected ${path}`);
  });
}

function listCalls() {
  return vi.mocked(apiFetch).mock.calls.filter(([path, init]) => path === "/server-groups" && !init).length;
}

describe("GroupsPage", () => {
  it("lists each group with its description and how many people hold a role in it", async () => {
    mockApi();
    render(<GroupsPage />);

    expect(await screen.findByRole("heading", { name: "Server groups" })).toBeInTheDocument();
    const staging = within(await screen.findByRole("row", { name: /staging/ }));
    expect(staging.getByText("2")).toBeInTheDocument();
    expect(staging.getByRole("button", { name: "Edit staging" })).toBeInTheDocument();
    expect(staging.getByRole("button", { name: "Delete staging" })).toBeInTheDocument();
    const production = within(screen.getByRole("row", { name: /production/ }));
    expect(production.getByText("Live servers")).toBeInTheDocument();
    expect(production.getByText("0")).toBeInTheDocument();
  });

  it("creates a group from New group and reloads", async () => {
    mockApi();
    render(<GroupsPage />);
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "New group" }));
    await user.type(screen.getByRole("textbox", { name: "Name" }), "staging");
    await user.click(screen.getByRole("button", { name: "Create group" }));

    expect(apiFetch).toHaveBeenCalledWith("/server-groups", {
      method: "POST",
      body: { name: "staging", description: "" },
    });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(listCalls()).toBe(2);
  });

  it("edits a group from its Edit button", async () => {
    mockApi();
    render(<GroupsPage />);
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Edit production" }));
    expect(screen.getByRole("heading", { name: "Edit production" })).toBeInTheDocument();
    await user.clear(screen.getByRole("textbox", { name: "Description" }));
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(apiFetch).toHaveBeenCalledWith("/server-groups/g-production", {
      method: "PATCH",
      body: { name: "production", description: "" },
    });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(listCalls()).toBe(2);
  });

  it("names the people who hold a role in a group before deleting it", async () => {
    mockApi();
    render(<GroupsPage />);
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Delete staging" }));
    expect(screen.getByText("These people lose their role in it: Ada Admin, Otto Operator.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Delete group" }));

    expect(apiFetch).toHaveBeenCalledWith("/server-groups/g-staging", { method: "DELETE" });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(listCalls()).toBe(2);
  });
});
