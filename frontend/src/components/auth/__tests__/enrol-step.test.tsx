import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { EnrolStep, type Enrolment } from "@/components/auth/enrol-step";
import { ApiError, apiFetch } from "@/lib/api";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), apiFetch: vi.fn() }));
vi.mock("@/lib/auth/navigate");

const ENROLMENT: Enrolment = {
  secret: "ABCDEFGHIJKLMNOP",
  uri: "otpauth://totp/MegooITAdmin:owner%40example.com?secret=ABCDEFGHIJKLMNOP&issuer=MegooITAdmin",
};
const CODES = Array.from({ length: 10 }, (_, i) => `AAAA-BBBB-CCCC-000${i}`);

beforeEach(() => {
  vi.mocked(apiFetch).mockReset();
});

function renderStep(enrolment?: Enrolment) {
  const props = { onDone: vi.fn(), onRestart: vi.fn() };
  render(<EnrolStep enrolment={enrolment} {...props} />);
  return props;
}

async function verify(code: string) {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Code"), code);
  await user.click(screen.getByRole("button", { name: "Verify" }));
}

describe("EnrolStep", () => {
  it("starts the enrolment once and shows the QR code and the key", async () => {
    vi.mocked(apiFetch).mockResolvedValue(ENROLMENT);
    renderStep();

    expect(await screen.findByText("ABCD EFGH IJKL MNOP")).toHaveClass("font-mono");
    expect(apiFetch).toHaveBeenCalledTimes(1);
    expect(apiFetch).toHaveBeenCalledWith("/auth/mfa/enrol", { method: "POST", body: {} });
    expect(screen.getByText("Set up your authenticator")).toBeInTheDocument();
    expect(
      screen.getByText("Scan the QR code with an authenticator app, then enter the 6-digit code it shows."),
    ).toBeInTheDocument();
    expect(screen.getByTitle("QR code for your authenticator").closest("svg")).toBeInTheDocument();
    expect(screen.getByText("Can't scan it? Enter this key:")).toBeInTheDocument();
  });

  it("posts nothing when the enrolment is given", () => {
    renderStep(ENROLMENT);

    expect(screen.getByText("ABCD EFGH IJKL MNOP")).toBeInTheDocument();
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("confirms the code and hands over the recovery codes", async () => {
    vi.mocked(apiFetch).mockResolvedValue({ status: "active", recovery_codes: CODES });
    const props = renderStep(ENROLMENT);
    const input = screen.getByLabelText("Code");
    expect(input).toHaveAttribute("inputmode", "numeric");
    expect(input).toHaveAttribute("autocomplete", "one-time-code");

    await verify("123456");

    expect(apiFetch).toHaveBeenCalledWith("/auth/mfa/enrol/confirm", { body: { code: "123456" } });
    expect(props.onDone).toHaveBeenCalledWith(CODES);
  });

  it("calls onDone with null when no recovery codes come back", async () => {
    vi.mocked(apiFetch).mockResolvedValue({ status: "active", recovery_codes: null });
    const props = renderStep(ENROLMENT);

    await verify("123456");

    expect(props.onDone).toHaveBeenCalledWith(null);
  });

  it("says when the code is wrong", async () => {
    vi.mocked(apiFetch).mockRejectedValue(new ApiError(401, "wrong_code"));
    const props = renderStep(ENROLMENT);

    await verify("000000");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "That code is not right. Check the clock of your phone and try again.",
    );
    expect(props.onDone).not.toHaveBeenCalled();
  });

  it("starts again with a notice when the sign-in has expired", async () => {
    vi.mocked(apiFetch).mockRejectedValue(new ApiError(401, "not_signed_in"));
    const props = renderStep(ENROLMENT);

    await verify("123456");

    expect(props.onRestart).toHaveBeenCalledWith("Your sign-in took too long. Start again.");
  });

  it("offers to try again when the enrolment cannot start", async () => {
    vi.mocked(apiFetch).mockRejectedValueOnce(new ApiError(0, "unreachable")).mockResolvedValueOnce(ENROLMENT);
    renderStep();

    expect(await screen.findByRole("alert")).toHaveTextContent("The server is not answering. Try again in a moment.");
    await userEvent.setup().click(screen.getByRole("button", { name: "Try again" }));

    expect(await screen.findByText("ABCD EFGH IJKL MNOP")).toBeInTheDocument();
    expect(apiFetch).toHaveBeenCalledTimes(2);
  });

  it("sends the person back to sign-in when starting finds no sign-in", async () => {
    vi.mocked(apiFetch).mockRejectedValue(new ApiError(401, "not_signed_in"));
    const props = renderStep();

    await vi.waitFor(() => expect(props.onRestart).toHaveBeenCalledWith("Your sign-in took too long. Start again."));
  });
});
