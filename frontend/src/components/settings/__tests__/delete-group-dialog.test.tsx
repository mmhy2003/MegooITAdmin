import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DeleteGroupDialog } from "@/components/settings/delete-group-dialog";
import { ApiError, apiFetch } from "@/lib/api";
import type { ServerGroup } from "@/lib/access";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), apiFetch: vi.fn() }));
vi.mock("@/lib/auth/navigate");

const STAGING: ServerGroup = {
  id: "g-staging",
  name: "staging",
  description: null,
  created_at: "2026-11-01T00:00:00Z",
  member_count: 2,
  server_count: 0,
  can_manage: true,
};

beforeEach(() => {
  vi.mocked(apiFetch).mockReset();
});

function renderDialog(props: Partial<Parameters<typeof DeleteGroupDialog>[0]> = {}) {
  const onDeleted = vi.fn();
  const onOpenChange = vi.fn();
  render(
    <DeleteGroupDialog
      group={STAGING}
      people={["Ada Admin", "Otto Operator"]}
      open
      onOpenChange={onOpenChange}
      onDeleted={onDeleted}
      {...props}
    />,
  );
  return { onDeleted, onOpenChange, user: userEvent.setup() };
}

describe("DeleteGroupDialog", () => {
  it("names the people who lose their role", () => {
    renderDialog();

    expect(screen.getByRole("heading", { name: "Delete staging?" })).toBeInTheDocument();
    expect(screen.getByText("These people lose their role in it: Ada Admin, Otto Operator.")).toBeInTheDocument();
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("says when nobody holds a role in it", () => {
    renderDialog({ people: [] });
    expect(screen.getByText("Nobody holds a role in it.")).toBeInTheDocument();
  });

  it("deletes the group only after Delete group", async () => {
    vi.mocked(apiFetch).mockResolvedValue(undefined);
    const { user, onDeleted } = renderDialog();

    await user.click(screen.getByRole("button", { name: "Delete group" }));

    expect(apiFetch).toHaveBeenCalledWith("/server-groups/g-staging", { method: "DELETE" });
    expect(onDeleted).toHaveBeenCalled();
  });

  it("closes on Cancel without deleting", async () => {
    const { user, onOpenChange, onDeleted } = renderDialog();

    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(apiFetch).not.toHaveBeenCalled();
    expect(onDeleted).not.toHaveBeenCalled();
  });

  it("shows a refusal", async () => {
    vi.mocked(apiFetch).mockRejectedValue(new ApiError(403, "forbidden"));
    const { user, onDeleted } = renderDialog();

    await user.click(screen.getByRole("button", { name: "Delete group" }));

    expect(await screen.findByText("You do not have the rights to do this.")).toBeInTheDocument();
    expect(onDeleted).not.toHaveBeenCalled();
  });

  it("shows the refusal of a group that holds servers", async () => {
    vi.mocked(apiFetch).mockRejectedValue(new ApiError(409, "group_has_servers"));
    const { user, onDeleted } = renderDialog();

    await user.click(screen.getByRole("button", { name: "Delete group" }));

    expect(await screen.findByText("This group still holds servers. Move or remove them first.")).toBeInTheDocument();
    expect(onDeleted).not.toHaveBeenCalled();
  });

  it("refuses to delete a group that holds servers, and links to them", async () => {
    const { user, onOpenChange } = renderDialog({ group: { ...STAGING, server_count: 3 } });

    expect(screen.getByRole("heading", { name: "staging still holds servers" })).toBeInTheDocument();
    expect(
      screen.getByText("Move or remove its 3 servers first. A group that holds servers cannot be deleted."),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Show its servers" })).toHaveAttribute("href", "/servers?group=g-staging");
    expect(screen.queryByRole("button", { name: "Delete group" })).not.toBeInTheDocument();
    expect(screen.queryByText(/lose their role/)).not.toBeInTheDocument();

    // The corner X is named Close too; this is the footer's visible one.
    const close = screen.getAllByRole("button", { name: "Close" }).find((b) => b.textContent === "Close");
    await user.click(close!);

    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("says server when the group holds one", () => {
    renderDialog({ group: { ...STAGING, server_count: 1 } });
    expect(
      screen.getByText("Move or remove its 1 server first. A group that holds servers cannot be deleted."),
    ).toBeInTheDocument();
  });

  it("is closed without a group", () => {
    renderDialog({ group: null, open: false });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
