import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AccessDialog } from "@/components/settings/access-dialog";
import { ApiError, apiFetch } from "@/lib/api";
import { type ServerGroup, switchesFor, type UserRow } from "@/lib/access";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), apiFetch: vi.fn() }));
vi.mock("@/lib/auth/navigate");

const GROUPS: ServerGroup[] = [
  { id: "g-production", name: "production", description: null, created_at: "2026-11-01T00:00:00Z", member_count: 0 },
  { id: "g-staging", name: "staging", description: null, created_at: "2026-11-01T00:00:00Z", member_count: 1 },
];

const ADA: UserRow = {
  id: "u-ada",
  name: "Ada Admin",
  email: "ada@example.com",
  platform_role: null,
  status: "active",
  mfa_enrolled: true,
  invite_expires_at: null,
  grants: [{ group_id: "g-staging", group_name: "staging", role: "admin", ...switchesFor("admin") }],
};

beforeEach(() => {
  vi.mocked(apiFetch).mockReset();
});

function renderDialog(props: Partial<Parameters<typeof AccessDialog>[0]> = {}) {
  const onSaved = vi.fn();
  const onStale = vi.fn();
  render(
    <AccessDialog
      user={ADA}
      groups={GROUPS}
      open
      onOpenChange={vi.fn()}
      onSaved={onSaved}
      onStale={onStale}
      {...props}
    />,
  );
  return { onSaved, onStale, user: userEvent.setup() };
}

async function giveOperatorOnProduction(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("combobox", { name: "Role in production" }));
  await user.click(await screen.findByRole("option", { name: "Operator" }));
}

describe("AccessDialog", () => {
  it("starts from the person's access and saves only once something differs", async () => {
    const { user } = renderDialog();

    expect(screen.getByRole("heading", { name: "Change access of Ada Admin" })).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Manage playbooks in staging" })).toBeChecked();
    const save = screen.getByRole("button", { name: "Save" });
    expect(save).toBeDisabled();

    await user.click(screen.getByRole("checkbox", { name: "View logs in staging" }));
    expect(save).toBeEnabled();
    await user.click(screen.getByRole("checkbox", { name: "View logs in staging" }));
    expect(save).toBeDisabled();
  });

  it("sends the whole access and reports it saved", async () => {
    vi.mocked(apiFetch).mockResolvedValue(undefined);
    const { user, onSaved, onStale } = renderDialog();

    await giveOperatorOnProduction(user);
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(apiFetch).toHaveBeenCalledWith("/users/u-ada/access", {
      method: "PUT",
      body: {
        platform_role: null,
        grants: [
          { group_id: "g-staging", role: "admin", ...switchesFor("admin") },
          { group_id: "g-production", role: "operator", ...switchesFor("operator") },
        ],
      },
    });
    expect(onSaved).toHaveBeenCalled();
    expect(onStale).not.toHaveBeenCalled();
  });

  it("asks for fresh groups when the server finds the access invalid", async () => {
    vi.mocked(apiFetch).mockRejectedValue(new ApiError(422, "invalid"));
    const { user, onSaved, onStale } = renderDialog();

    await giveOperatorOnProduction(user);
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByText("Check the fields and try again.")).toBeInTheDocument();
    expect(onStale).toHaveBeenCalled();
    expect(onSaved).not.toHaveBeenCalled();
  });

  it("says when the Owner tries to change their own account", async () => {
    vi.mocked(apiFetch).mockRejectedValue(new ApiError(409, "own_account"));
    const { user, onSaved, onStale } = renderDialog();

    await user.click(screen.getByRole("radio", { name: "Auditor" }));
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(apiFetch).toHaveBeenCalledWith("/users/u-ada/access", {
      method: "PUT",
      body: { platform_role: "auditor", grants: [] },
    });
    expect(await screen.findByText("You cannot change your own account here.")).toBeInTheDocument();
    expect(onSaved).not.toHaveBeenCalled();
    expect(onStale).not.toHaveBeenCalled();
  });

  it("is closed without a person", () => {
    renderDialog({ user: null, open: false });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
