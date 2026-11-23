import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { PasswordDialog } from "@/components/profile/password-dialog";
import { ApiError, apiFetch } from "@/lib/api";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), apiFetch: vi.fn() }));
vi.mock("@/lib/auth/navigate");

beforeEach(() => {
  vi.mocked(apiFetch).mockReset();
});

async function change(current: string, next: string, repeat: string) {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Current password"), current);
  await user.type(screen.getByLabelText("New password"), next);
  await user.type(screen.getByLabelText("Repeat the new password"), repeat);
  await user.click(screen.getByRole("button", { name: "Change password" }));
}

describe("PasswordDialog", () => {
  it("posts nothing and says so when the new passwords do not match", async () => {
    render(<PasswordDialog open onOpenChange={vi.fn()} onChanged={vi.fn()} />);
    expect(screen.getByRole("dialog", { name: "Change password" })).toBeInTheDocument();

    await change("the old password", "a new long password", "another long password");

    expect(screen.getByRole("alert")).toHaveTextContent("The passwords do not match.");
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("posts nothing when the new password is too short", async () => {
    render(<PasswordDialog open onOpenChange={vi.fn()} onChanged={vi.fn()} />);

    await change("the old password", "short", "short");

    expect(screen.getByRole("alert")).toHaveTextContent("Use 12 to 128 characters.");
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("says when the current password is wrong", async () => {
    vi.mocked(apiFetch).mockRejectedValue(new ApiError(401, "wrong_password"));
    const onChanged = vi.fn();
    render(<PasswordDialog open onOpenChange={vi.fn()} onChanged={onChanged} />);

    await change("wrong", "a new long password", "a new long password");

    expect(await screen.findByRole("alert")).toHaveTextContent("The current password is wrong.");
    expect(onChanged).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Change password" })).toBeEnabled();
  });

  it("says when the account is locked", async () => {
    vi.mocked(apiFetch).mockRejectedValue(new ApiError(401, "locked"));
    render(<PasswordDialog open onOpenChange={vi.fn()} onChanged={vi.fn()} />);

    await change("wrong", "a new long password", "a new long password");

    expect(await screen.findByRole("alert")).toHaveTextContent("This account is locked for 15 minutes");
  });

  it("posts the current and the new password, then calls onChanged", async () => {
    vi.mocked(apiFetch).mockResolvedValue({ status: "ok" });
    const onChanged = vi.fn();
    render(<PasswordDialog open onOpenChange={vi.fn()} onChanged={onChanged} />);

    await change("the old password", "a new long password", "a new long password");

    expect(apiFetch).toHaveBeenCalledWith("/auth/password", {
      method: "POST",
      body: { current_password: "the old password", new_password: "a new long password" },
    });
    expect(onChanged).toHaveBeenCalledOnce();
    expect(screen.getByLabelText("Current password")).toHaveValue("");
  });

  it("disables the button while the request runs", async () => {
    vi.mocked(apiFetch).mockReturnValue(new Promise(() => {}));
    render(<PasswordDialog open onOpenChange={vi.fn()} onChanged={vi.fn()} />);

    await change("the old password", "a new long password", "a new long password");

    expect(screen.getByRole("button", { name: "Change password" })).toBeDisabled();
  });
});
