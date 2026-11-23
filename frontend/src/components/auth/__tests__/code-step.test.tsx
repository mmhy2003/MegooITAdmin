import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CodeStep } from "@/components/auth/code-step";
import { ApiError, apiFetch } from "@/lib/api";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), apiFetch: vi.fn() }));
vi.mock("@/lib/auth/navigate");

beforeEach(() => {
  vi.mocked(apiFetch).mockReset();
});

function renderStep() {
  const props = { onDone: vi.fn(), onUseRecovery: vi.fn(), onLocked: vi.fn(), onRestart: vi.fn() };
  render(<CodeStep {...props} />);
  return props;
}

async function verify(code: string) {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Code"), code);
  await user.click(screen.getByRole("button", { name: "Verify" }));
}

describe("CodeStep", () => {
  it("posts the code as a TOTP code and calls onDone", async () => {
    vi.mocked(apiFetch).mockResolvedValue({ status: "active" });
    const props = renderStep();
    expect(screen.getByText("Enter your code")).toBeInTheDocument();
    const input = screen.getByLabelText("Code");
    expect(input).toHaveAttribute("inputmode", "numeric");
    expect(input).toHaveAttribute("autocomplete", "one-time-code");

    await verify("123456");

    expect(apiFetch).toHaveBeenCalledWith("/auth/login/mfa", { body: { code: "123456", method: "totp" } });
    expect(props.onDone).toHaveBeenCalled();
  });

  it("calls onLocked when the account is locked", async () => {
    vi.mocked(apiFetch).mockRejectedValue(new ApiError(423, "locked"));
    const props = renderStep();

    await verify("123456");

    expect(props.onLocked).toHaveBeenCalled();
    expect(props.onDone).not.toHaveBeenCalled();
  });

  it("starts again with a notice when the sign-in has expired", async () => {
    vi.mocked(apiFetch).mockRejectedValue(new ApiError(401, "not_signed_in"));
    const props = renderStep();

    await verify("123456");

    expect(props.onRestart).toHaveBeenCalledWith("Your sign-in took too long. Start again.");
  });

  it("says when the code is wrong", async () => {
    vi.mocked(apiFetch).mockRejectedValue(new ApiError(401, "wrong_code"));
    const props = renderStep();

    await verify("000000");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "That code is not right. Check the clock of your phone and try again.",
    );
    expect(props.onDone).not.toHaveBeenCalled();
  });

  it("switches to a recovery code, or starts again", async () => {
    const user = userEvent.setup();
    const props = renderStep();

    await user.click(screen.getByRole("button", { name: "Use a recovery code" }));
    expect(props.onUseRecovery).toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Start again" }));
    expect(props.onRestart).toHaveBeenCalledWith("");
    expect(apiFetch).not.toHaveBeenCalled();
  });
});
