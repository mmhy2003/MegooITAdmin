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

    expect(await screen.findByText("Only the Owner can do this.")).toBeInTheDocument();
    expect(onDeleted).not.toHaveBeenCalled();
  });

  it("is closed without a group", () => {
    renderDialog({ group: null, open: false });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
