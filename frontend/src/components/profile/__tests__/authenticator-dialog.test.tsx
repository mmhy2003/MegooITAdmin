import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Enrolment } from "@/components/auth/enrol-step";
import { AuthenticatorDialog } from "@/components/profile/authenticator-dialog";
import { ApiError, apiFetch } from "@/lib/api";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), apiFetch: vi.fn() }));
vi.mock("@/lib/auth/navigate");

const ENROLMENT: Enrolment = {
  secret: "ABCDEFGHIJKLMNOP",
  uri: "otpauth://totp/MegooITAdmin:owner%40example.com?secret=ABCDEFGHIJKLMNOP&issuer=MegooITAdmin",
};

beforeEach(() => {
  vi.mocked(apiFetch).mockReset();
});

function renderDialog() {
  const props = { onOpenChange: vi.fn(), onReplaced: vi.fn() };
  render(<AuthenticatorDialog open {...props} />);
  return props;
}

describe("AuthenticatorDialog", () => {
  it("posts the code with the method totp", async () => {
    vi.mocked(apiFetch).mockResolvedValue(ENROLMENT);
    renderDialog();
    expect(screen.getByRole("dialog", { name: "Replace authenticator" })).toBeInTheDocument();
    expect(screen.getByText("Enter a code from your current authenticator.")).toBeInTheDocument();
    const user = userEvent.setup();

    await user.type(screen.getByLabelText("Code"), "123456");
    await user.click(screen.getByRole("button", { name: "Continue" }));

    expect(apiFetch).toHaveBeenCalledWith("/auth/mfa/enrol", {
      method: "POST",
      body: { code: "123456", method: "totp" },
    });
  });

  it("posts a recovery code with the method recovery_code when the box is ticked", async () => {
    vi.mocked(apiFetch).mockResolvedValue(ENROLMENT);
    renderDialog();
    const user = userEvent.setup();

    await user.click(screen.getByLabelText("Use a recovery code instead"));
    await user.type(screen.getByLabelText("Recovery code"), "AAAA-BBBB-CCCC-0001");
    await user.click(screen.getByRole("button", { name: "Continue" }));

    expect(apiFetch).toHaveBeenCalledWith("/auth/mfa/enrol", {
      method: "POST",
      body: { code: "AAAA-BBBB-CCCC-0001", method: "recovery_code" },
    });
  });

  it("moves to the QR code after a right code", async () => {
    vi.mocked(apiFetch).mockResolvedValue(ENROLMENT);
    renderDialog();
    const user = userEvent.setup();

    await user.type(screen.getByLabelText("Code"), "123456");
    await user.click(screen.getByRole("button", { name: "Continue" }));

    expect(await screen.findByText("Set up your authenticator")).toBeInTheDocument();
    expect(screen.getByText("ABCD EFGH IJKL MNOP")).toBeInTheDocument();
  });

  it("says when the code is wrong and stays on the proof", async () => {
    vi.mocked(apiFetch).mockRejectedValue(new ApiError(401, "wrong_code"));
    renderDialog();
    const user = userEvent.setup();

    await user.type(screen.getByLabelText("Code"), "000000");
    await user.click(screen.getByRole("button", { name: "Continue" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("That code is not right.");
    expect(screen.queryByText("Set up your authenticator")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Continue" })).toBeEnabled();
  });

  it("goes back to the proof with the notice when the enrolment must start again", async () => {
    vi.mocked(apiFetch).mockImplementation(async (path: string) => {
      if (path === "/auth/mfa/enrol") return ENROLMENT;
      throw new ApiError(401, "not_signed_in");
    });
    renderDialog();
    const user = userEvent.setup();

    await user.type(screen.getByLabelText("Code"), "123456");
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await user.type(await screen.findByLabelText("Code"), "654321");
    await user.click(screen.getByRole("button", { name: "Verify" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Your sign-in took too long. Start again.");
    expect(screen.getByRole("button", { name: "Continue" })).toBeInTheDocument();
  });

  it("calls onReplaced when the new authenticator is verified", async () => {
    vi.mocked(apiFetch).mockImplementation(async (path: string) => {
      if (path === "/auth/mfa/enrol") return ENROLMENT;
      if (path === "/auth/mfa/enrol/confirm") return { recovery_codes: null };
      throw new Error(`unexpected ${path}`);
    });
    const { onReplaced } = renderDialog();
    const user = userEvent.setup();

    await user.type(screen.getByLabelText("Code"), "123456");
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await user.type(await screen.findByLabelText("Code"), "654321");
    await user.click(screen.getByRole("button", { name: "Verify" }));

    expect(apiFetch).toHaveBeenLastCalledWith("/auth/mfa/enrol/confirm", { body: { code: "654321" } });
    expect(onReplaced).toHaveBeenCalledOnce();
  });
});
