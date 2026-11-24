import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { GroupDialog } from "@/components/settings/group-dialog";
import { ApiError, apiFetch } from "@/lib/api";
import type { ServerGroup } from "@/lib/access";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), apiFetch: vi.fn() }));
vi.mock("@/lib/auth/navigate");

const STAGING: ServerGroup = {
  id: "g-staging",
  name: "staging",
  description: "Pre-release servers",
  created_at: "2026-11-01T00:00:00Z",
  member_count: 2,
  server_count: 0,
  can_manage: true,
};

beforeEach(() => {
  vi.mocked(apiFetch).mockReset();
});

function renderDialog(props: Partial<Parameters<typeof GroupDialog>[0]> = {}) {
  const onSaved = vi.fn();
  render(<GroupDialog open onOpenChange={vi.fn()} onSaved={onSaved} {...props} />);
  return { onSaved, user: userEvent.setup() };
}

describe("GroupDialog", () => {
  it("creates a group with its name and description", async () => {
    vi.mocked(apiFetch).mockResolvedValue({ ...STAGING, id: "g-new", name: "production" });
    const { user, onSaved } = renderDialog();

    expect(screen.getByRole("heading", { name: "New server group" })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Name" })).toHaveAccessibleDescription("1 to 64 characters.");
    await user.type(screen.getByRole("textbox", { name: "Name" }), "production");
    await user.type(screen.getByRole("textbox", { name: "Description" }), "Live servers");
    await user.click(screen.getByRole("button", { name: "Create group" }));

    expect(apiFetch).toHaveBeenCalledWith("/server-groups", {
      method: "POST",
      body: { name: "production", description: "Live servers" },
    });
    expect(onSaved).toHaveBeenCalled();
  });

  it("edits a group, and saves only once something differs", async () => {
    vi.mocked(apiFetch).mockResolvedValue(STAGING);
    const { user, onSaved } = renderDialog({ group: STAGING });

    expect(screen.getByRole("heading", { name: "Edit staging" })).toBeInTheDocument();
    const name = screen.getByRole("textbox", { name: "Name" });
    expect(name).toHaveValue("staging");
    expect(screen.getByRole("textbox", { name: "Description" })).toHaveValue("Pre-release servers");
    const save = screen.getByRole("button", { name: "Save" });
    expect(save).toBeDisabled();

    await user.type(name, "-eu");
    expect(save).toBeEnabled();
    await user.type(name, "{Backspace}{Backspace}{Backspace}");
    expect(save).toBeDisabled();

    await user.type(name, "-eu");
    await user.click(save);

    expect(apiFetch).toHaveBeenCalledWith("/server-groups/g-staging", {
      method: "PATCH",
      body: { name: "staging-eu", description: "Pre-release servers" },
    });
    expect(onSaved).toHaveBeenCalled();
  });

  it("says when another group has the name", async () => {
    vi.mocked(apiFetch).mockRejectedValue(new ApiError(409, "name_taken"));
    const { user, onSaved } = renderDialog();

    await user.type(screen.getByRole("textbox", { name: "Name" }), "Staging");
    await user.click(screen.getByRole("button", { name: "Create group" }));

    expect(await screen.findByText("A server group with this name exists already.")).toBeInTheDocument();
    expect(onSaved).not.toHaveBeenCalled();
  });

  it("is closed when not open", () => {
    renderDialog({ open: false });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
