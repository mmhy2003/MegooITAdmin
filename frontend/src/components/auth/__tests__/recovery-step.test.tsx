import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { RecoveryStep } from "@/components/auth/recovery-step";
import { ApiError, apiFetch } from "@/lib/api";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), apiFetch: vi.fn() }));
vi.mock("@/lib/auth/navigate");

beforeEach(() => {
  vi.mocked(apiFetch).mockReset();
});

function renderStep() {
  const props = { onDone: vi.fn(), onUseCode: vi.fn(), onLocked: vi.fn(), onRestart: vi.fn() };
  render(<RecoveryStep {...props} />);
  return props;
}

async function verify(code: string) {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Recovery code"), code);
  await user.click(screen.getByRole("button", { name: "Verify" }));
}

describe("RecoveryStep", () => {
  it("posts the code as a recovery code and calls onDone", async () => {
    vi.mocked(apiFetch).mockResolvedValue({ status: "active" });
    const props = renderStep();
    expect(screen.getByText("Use a recovery code")).toBeInTheDocument();
    expect(screen.getByLabelText("Recovery code")).toHaveAttribute("placeholder", "XXXX-XXXX-XXXX-XXXX");

    await verify("ABCD-EFGH-JKLM-NPQR");

    expect(apiFetch).toHaveBeenCalledWith("/auth/login/mfa", {
      body: { code: "ABCD-EFGH-JKLM-NPQR", method: "recovery_code" },
    });
    expect(props.onDone).toHaveBeenCalled();
  });

  it("calls onLocked when the account is locked", async () => {
    vi.mocked(apiFetch).mockRejectedValue(new ApiError(423, "locked"));
    const props = renderStep();

    await verify("ABCD-EFGH-JKLM-NPQR");

    expect(props.onLocked).toHaveBeenCalled();
  });

  it("starts again with a notice when the sign-in has expired", async () => {
    vi.mocked(apiFetch).mockRejectedValue(new ApiError(401, "not_signed_in"));
    const props = renderStep();

    await verify("ABCD-EFGH-JKLM-NPQR");

    expect(props.onRestart).toHaveBeenCalledWith("Your sign-in took too long. Start again.");
  });

  it("says when the code is wrong", async () => {
    vi.mocked(apiFetch).mockRejectedValue(new ApiError(401, "wrong_code"));
    renderStep();

    await verify("ABCD-EFGH-JKLM-NPQR");

    expect(await screen.findByRole("alert")).toHaveTextContent("That code is not right.");
  });

  it("switches back to the authenticator", async () => {
    const props = renderStep();

    await userEvent.setup().click(screen.getByRole("button", { name: "Use your authenticator instead" }));

    expect(props.onUseCode).toHaveBeenCalled();
    expect(apiFetch).not.toHaveBeenCalled();
  });
});
