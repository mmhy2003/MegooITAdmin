import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DisableDialog } from "@/components/settings/disable-dialog";
import { ApiError, apiFetch } from "@/lib/api";
import type { UserRow } from "@/lib/access";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), apiFetch: vi.fn() }));
vi.mock("@/lib/auth/navigate");

const ADA: UserRow = {
  id: "u-ada",
  name: "Ada Admin",
  email: "ada@example.com",
  platform_role: "owner",
  status: "active",
  mfa_enrolled: true,
  invite_expires_at: null,
  grants: [],
};

beforeEach(() => {
  vi.mocked(apiFetch).mockReset();
});

function renderDialog(props: Partial<Parameters<typeof DisableDialog>[0]> = {}) {
  const onDone = vi.fn();
  const onOpenChange = vi.fn();
  render(<DisableDialog user={ADA} open onOpenChange={onOpenChange} onDone={onDone} {...props} />);
  return { onDone, onOpenChange, user: userEvent.setup() };
}

describe("DisableDialog", () => {
  it("asks first and says what disabling does", () => {
    renderDialog();

    expect(screen.getByRole("heading", { name: "Disable Ada Admin?" })).toBeInTheDocument();
    expect(
      screen.getByText(
        "They are signed out at once and cannot sign in until an Owner enables the account. Their access and history stay.",
      ),
    ).toBeInTheDocument();
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("disables the person only after Disable", async () => {
    vi.mocked(apiFetch).mockResolvedValue(undefined);
    const { user, onDone } = renderDialog();

    await user.click(screen.getByRole("button", { name: "Disable" }));

    expect(apiFetch).toHaveBeenCalledWith("/users/u-ada/disable", { method: "POST" });
    expect(onDone).toHaveBeenCalled();
  });

  it("closes on Cancel without posting", async () => {
    const { user, onOpenChange, onDone } = renderDialog();

    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(apiFetch).not.toHaveBeenCalled();
    expect(onDone).not.toHaveBeenCalled();
  });

  it.each([
    ["last_owner", "At least one enabled Owner must remain."],
    ["own_account", "You cannot change your own account here."],
  ])("shows the refusal %s", async (detail, text) => {
    vi.mocked(apiFetch).mockRejectedValue(new ApiError(409, detail));
    const { user, onDone } = renderDialog();

    await user.click(screen.getByRole("button", { name: "Disable" }));

    expect(await screen.findByText(text)).toBeInTheDocument();
    expect(onDone).not.toHaveBeenCalled();
  });

  it("is closed without a person", () => {
    renderDialog({ user: null, open: false });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
