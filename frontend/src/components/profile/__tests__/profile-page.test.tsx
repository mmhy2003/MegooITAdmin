import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { formatTime, ProfilePage, type Me } from "@/components/profile/profile-page";
import { ApiError, apiFetch } from "@/lib/api";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), apiFetch: vi.fn() }));
vi.mock("@/lib/auth/navigate");

const ME: Me = {
  user: { id: "u1", name: "Ada Owner", email: "owner@example.com", is_owner: true },
  password_changed_at: "2026-11-20T09:30:00Z",
  totp_confirmed_at: "2026-11-20T09:31:00Z",
  recovery_codes_left: 10,
};

const ENROLMENT = { secret: "ABCDEFGHIJKLMNOP", uri: "otpauth://totp/x?secret=ABCDEFGHIJKLMNOP" };

beforeEach(() => {
  vi.mocked(apiFetch).mockReset();
});

function mockApi(password: () => Promise<unknown> = async () => ({ status: "ok" })) {
  vi.mocked(apiFetch).mockImplementation(async (path: string) => {
    if (path === "/auth/me") return ME;
    if (path === "/auth/password") return password();
    throw new Error(`unexpected ${path}`);
  });
}

describe("ProfilePage", () => {
  it("shows the name, the email and the Owner badge", async () => {
    mockApi();
    render(<ProfilePage />);

    expect(await screen.findByText("Ada Owner")).toBeInTheDocument();
    expect(screen.getByText("owner@example.com")).toBeInTheDocument();
    expect(screen.getByText("Owner")).toBeInTheDocument();
    expect(screen.getByText(`Last changed ${formatTime(ME.password_changed_at)}`)).toBeInTheDocument();
    expect(apiFetch).toHaveBeenCalledWith("/auth/me");
  });

  it("shows no Owner badge for someone else", async () => {
    vi.mocked(apiFetch).mockResolvedValue({ ...ME, user: { ...ME.user, is_owner: false } });
    render(<ProfilePage />);

    expect(await screen.findByText("Ada Owner")).toBeInTheDocument();
    expect(screen.queryByText("Owner")).not.toBeInTheDocument();
  });

  it("says when the profile cannot be loaded", async () => {
    vi.mocked(apiFetch).mockRejectedValue(new ApiError(0, "unreachable"));
    render(<ProfilePage />);

    expect(await screen.findByRole("alert")).toHaveTextContent("The server is not answering. Try again in a moment.");
  });

  it("shows when the authenticator was added and how many recovery codes are left", async () => {
    vi.mocked(apiFetch).mockResolvedValue({ ...ME, recovery_codes_left: 3 });
    render(<ProfilePage />);

    expect(await screen.findByText("3 of 10 recovery codes left")).toBeInTheDocument();
    expect(screen.getByText(`Authenticator app added ${formatTime("2026-11-20T09:31:00Z")}`)).toBeInTheDocument();
  });

  it("opens the authenticator and the recovery codes dialogs", async () => {
    mockApi();
    render(<ProfilePage />);
    await screen.findByText("Ada Owner");
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Replace authenticator" }));
    expect(screen.getByRole("dialog", { name: "Replace authenticator" })).toBeInTheDocument();
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "New recovery codes" }));
    expect(screen.getByRole("dialog", { name: "New recovery codes" })).toBeInTheDocument();
  });

  it("shows the notice and loads the profile again after the authenticator is replaced", async () => {
    vi.mocked(apiFetch).mockImplementation(async (path: string) => {
      if (path === "/auth/me") return ME;
      if (path === "/auth/mfa/enrol") return ENROLMENT;
      if (path === "/auth/mfa/enrol/confirm") return { recovery_codes: null };
      throw new Error(`unexpected ${path}`);
    });
    render(<ProfilePage />);
    await screen.findByText("Ada Owner");
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Replace authenticator" }));
    await user.type(screen.getByLabelText("Code"), "123456");
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await user.type(await screen.findByLabelText("Code"), "654321");
    await user.click(screen.getByRole("button", { name: "Verify" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Authenticator replaced. Your other sessions were signed out.",
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(vi.mocked(apiFetch).mock.calls.filter(([path]) => path === "/auth/me")).toHaveLength(2);
  });

  it("opens the password dialog", async () => {
    mockApi();
    render(<ProfilePage />);
    await screen.findByText("Ada Owner");

    await userEvent.setup().click(screen.getByRole("button", { name: "Change password" }));

    expect(screen.getByRole("dialog", { name: "Change password" })).toBeInTheDocument();
  });

  it("closes the dialog, shows the notice and loads the profile again after a change", async () => {
    mockApi();
    render(<ProfilePage />);
    await screen.findByText("Ada Owner");
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Change password" }));
    await user.type(screen.getByLabelText("Current password"), "the old password");
    await user.type(screen.getByLabelText("New password"), "a new long password");
    await user.type(screen.getByLabelText("Repeat the new password"), "a new long password");
    await user.click(screen.getByRole("button", { name: "Change password" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Password changed. Your other sessions were signed out.");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(vi.mocked(apiFetch).mock.calls.filter(([path]) => path === "/auth/me")).toHaveLength(2);
  });
});

describe("formatTime", () => {
  it("formats a time in British English", () => {
    expect(formatTime("2026-11-20T09:30:00Z")).toMatch(/20 Nov 2026/);
  });
});
