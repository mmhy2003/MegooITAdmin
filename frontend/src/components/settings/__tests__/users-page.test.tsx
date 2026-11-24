import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { formatTime } from "@/components/profile/profile-page";
import { UsersPage } from "@/components/settings/users-page";
import { ApiError, apiFetch } from "@/lib/api";
import { type InviteLink, type ServerGroup, switchesFor, type UserRow } from "@/lib/access";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), apiFetch: vi.fn() }));
vi.mock("@/lib/auth/navigate");

const GROUPS: ServerGroup[] = [
  { id: "g-production", name: "production", description: null, created_at: "2026-11-01T00:00:00Z", member_count: 1, server_count: 0, can_manage: true },
  { id: "g-staging", name: "staging", description: null, created_at: "2026-11-01T00:00:00Z", member_count: 1, server_count: 0, can_manage: true },
];

const OWNER: UserRow = {
  id: "u-owner",
  name: "Olive Owner",
  email: "owner@example.com",
  platform_role: "owner",
  status: "active",
  mfa_enrolled: true,
  invite_expires_at: null,
  grants: [],
};

const ADA: UserRow = {
  id: "u-ada",
  name: "Ada Admin",
  email: "ada@example.com",
  platform_role: null,
  status: "active",
  mfa_enrolled: true,
  invite_expires_at: null,
  grants: [
    { group_id: "g-production", group_name: "production", role: "operator", ...switchesFor("operator") },
    { group_id: "g-staging", group_name: "staging", role: "admin", ...switchesFor("admin") },
  ],
};

const BEN: UserRow = {
  id: "u-ben",
  name: "Ben Invited",
  email: "ben@example.com",
  platform_role: "auditor",
  status: "invited",
  mfa_enrolled: false,
  invite_expires_at: "2026-12-01T10:00:00Z",
  grants: [],
};

const CY: UserRow = {
  id: "u-cy",
  name: "Cy Disabled",
  email: "cy@example.com",
  platform_role: null,
  status: "disabled",
  mfa_enrolled: false,
  invite_expires_at: null,
  grants: [],
};

const LINK: InviteLink = { user_id: "u-new", token: "tok-new", expires_at: "2026-12-02T10:00:00Z" };
const RENEWED: InviteLink = { user_id: BEN.id, token: "tok-ben", expires_at: "2026-12-03T10:00:00Z" };

beforeEach(() => {
  vi.mocked(apiFetch).mockReset();
});

function mockApi() {
  vi.mocked(apiFetch).mockImplementation(async (path: string, init?: { method?: string }) => {
    if (path === "/users" && init?.method === "POST") return LINK;
    if (path === `/users/${ADA.id}/access` && init?.method === "PUT") return undefined;
    if (path === `/users/${BEN.id}/invite` && init?.method === "POST") return RENEWED;
    if (/^\/users\/u-\w+\/(disable|enable|mfa-reset)$/.test(path) && init?.method === "POST") return undefined;
    if (path === "/users") return [ADA, BEN, CY, OWNER];
    if (path === "/server-groups") return GROUPS;
    throw new Error(`unexpected ${path}`);
  });
}

function rowOf(name: string) {
  return screen.getByRole("row", { name: new RegExp(name) });
}

async function menuItemsOf(name: string) {
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: `Actions for ${name}` }));
  const items = (await screen.findAllByRole("menuitem")).map((item) => item.textContent);
  await user.keyboard("{Escape}");
  return items;
}

describe("UsersPage", () => {
  it("lists each person with their access, status and two-step verification", async () => {
    mockApi();
    render(<UsersPage currentUserId={OWNER.id} />);

    expect(await screen.findByRole("heading", { name: "People" })).toBeInTheDocument();
    const ada = within(await screen.findByRole("row", { name: /Ada Admin/ }));
    expect(ada.getByText("ada@example.com")).toBeInTheDocument();
    expect(ada.getByText("Operator · production")).toBeInTheDocument();
    expect(ada.getByText("Admin · staging")).toBeInTheDocument();
    expect(ada.getByText("Active")).toBeInTheDocument();
    expect(ada.getByText("On")).toBeInTheDocument();

    const ben = within(rowOf("Ben Invited"));
    expect(ben.getByText("Auditor")).toBeInTheDocument();
    expect(ben.getByText(`Invited · link expires ${formatTime(BEN.invite_expires_at!)}`)).toBeInTheDocument();
    expect(ben.getByText("Not set up")).toBeInTheDocument();

    const cy = within(rowOf("Cy Disabled"));
    expect(cy.getByText("No access")).toBeInTheDocument();
    expect(cy.getByText("Disabled")).toBeInTheDocument();
  });

  it("marks the Owner's own row and gives it no menu", async () => {
    mockApi();
    render(<UsersPage currentUserId={OWNER.id} />);

    const own = within(await screen.findByRole("row", { name: /Olive Owner/ }));
    expect(own.getByText("You")).toBeInTheDocument();
    expect(own.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Actions for Olive Owner" })).not.toBeInTheDocument();
  });

  it("offers the actions that fit each status", async () => {
    mockApi();
    render(<UsersPage currentUserId={OWNER.id} />);
    await screen.findByRole("row", { name: /Ada Admin/ });

    expect(await menuItemsOf("Ada Admin")).toEqual(["Change access", "Reset two-step verification", "Disable"]);
    expect(await menuItemsOf("Ben Invited")).toEqual(["Change access", "New invite link", "Disable"]);
    expect(await menuItemsOf("Cy Disabled")).toEqual(["Change access", "Enable"]);
  });

  it("changes a person's access from their menu and says it is saved", async () => {
    mockApi();
    render(<UsersPage currentUserId={OWNER.id} />);
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Actions for Ada Admin" }));
    await user.click(await screen.findByRole("menuitem", { name: "Change access" }));
    const dialog = within(await screen.findByRole("dialog", { name: "Change access of Ada Admin" }));
    expect(dialog.getByRole("checkbox", { name: "Manage playbooks in staging" })).toBeChecked();
    await user.click(dialog.getByRole("checkbox", { name: "View logs in staging" }));
    await user.click(dialog.getByRole("button", { name: "Save" }));

    expect(apiFetch).toHaveBeenCalledWith(`/users/${ADA.id}/access`, expect.objectContaining({ method: "PUT" }));
    expect(await screen.findByText("Access of Ada Admin saved.")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await waitFor(() => expect(vi.mocked(apiFetch).mock.calls.filter(([p]) => p === "/users")).toHaveLength(2));
  });

  async function choose(name: string, action: string) {
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: `Actions for ${name}` }));
    await user.click(await screen.findByRole("menuitem", { name: action }));
    return user;
  }

  function usersLoads() {
    return vi.mocked(apiFetch).mock.calls.filter(([p]) => p === "/users").length;
  }

  it("asks before disabling a person and disables them only after Disable", async () => {
    mockApi();
    render(<UsersPage currentUserId={OWNER.id} />);

    const user = await choose("Ada Admin", "Disable");
    const dialog = within(await screen.findByRole("dialog", { name: "Disable Ada Admin?" }));
    expect(apiFetch).not.toHaveBeenCalledWith(`/users/${ADA.id}/disable`, expect.anything());
    await user.click(dialog.getByRole("button", { name: "Disable" }));

    expect(apiFetch).toHaveBeenCalledWith(`/users/${ADA.id}/disable`, { method: "POST" });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await waitFor(() => expect(usersLoads()).toBe(2));
  });

  it("enables a disabled person and says they can sign in", async () => {
    mockApi();
    render(<UsersPage currentUserId={OWNER.id} />);

    await choose("Cy Disabled", "Enable");

    expect(apiFetch).toHaveBeenCalledWith(`/users/${CY.id}/enable`, { method: "POST" });
    expect(await screen.findByText("Cy Disabled can sign in again.")).toBeInTheDocument();
    await waitFor(() => expect(usersLoads()).toBe(2));
  });

  it("resets a person's two-step verification and says what happens next", async () => {
    mockApi();
    render(<UsersPage currentUserId={OWNER.id} />);

    await choose("Ada Admin", "Reset two-step verification");

    expect(apiFetch).toHaveBeenCalledWith(`/users/${ADA.id}/mfa-reset`, { method: "POST" });
    expect(
      await screen.findByText(
        "Two-step verification of Ada Admin is reset. They set up a new authenticator at their next sign-in.",
      ),
    ).toBeInTheDocument();
    await waitFor(() => expect(usersLoads()).toBe(2));
  });

  it("makes a new invite link and shows it once", async () => {
    mockApi();
    render(<UsersPage currentUserId={OWNER.id} />);

    await choose("Ben Invited", "New invite link");

    expect(apiFetch).toHaveBeenCalledWith(`/users/${BEN.id}/invite`, { method: "POST" });
    const linkDialog = within(await screen.findByRole("dialog", { name: "Invite link for Ben Invited" }));
    expect(linkDialog.getByRole("textbox", { name: "Invite link" })).toHaveValue(
      `${window.location.origin}/invite#tok-ben`,
    );
    await waitFor(() => expect(usersLoads()).toBe(2));
  });

  it("shows the text of a refusal", async () => {
    mockApi();
    const listed = vi.mocked(apiFetch).getMockImplementation()!;
    vi.mocked(apiFetch).mockImplementation(async (path, init) => {
      if (path === `/users/${CY.id}/enable`) throw new ApiError(409, "own_account");
      return listed(path, init);
    });
    render(<UsersPage currentUserId={OWNER.id} />);

    await choose("Cy Disabled", "Enable");

    expect(await screen.findByText("You cannot change your own account here.")).toBeInTheDocument();
    expect(screen.queryByText("Cy Disabled can sign in again.")).not.toBeInTheDocument();
  });

  it("invites a person, shows the link once and lists them", async () => {
    mockApi();
    render(<UsersPage currentUserId={OWNER.id} />);
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Invite person" }));
    const dialog = within(await screen.findByRole("dialog", { name: "Invite a person" }));
    await user.type(dialog.getByLabelText("Name"), "Dee New");
    await user.type(dialog.getByLabelText("Email"), "dee@example.com");
    await user.click(dialog.getByRole("radio", { name: "Auditor" }));
    await user.click(dialog.getByRole("button", { name: "Create invite link" }));

    expect(apiFetch).toHaveBeenCalledWith("/users", {
      method: "POST",
      body: { name: "Dee New", email: "dee@example.com", platform_role: "auditor", grants: [] },
    });
    const linkDialog = within(await screen.findByRole("dialog", { name: "Invite link for Dee New" }));
    expect(linkDialog.getByRole("textbox", { name: "Invite link" })).toHaveValue(
      `${window.location.origin}/invite#tok-new`,
    );
    expect(screen.queryByRole("dialog", { name: "Invite a person" })).not.toBeInTheDocument();
    await waitFor(() => expect(vi.mocked(apiFetch).mock.calls.filter(([p]) => p === "/users")).toHaveLength(3));

    await user.click(linkDialog.getByRole("button", { name: "Done" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(screen.queryByDisplayValue(/tok-new/)).not.toBeInTheDocument();
  });
});
