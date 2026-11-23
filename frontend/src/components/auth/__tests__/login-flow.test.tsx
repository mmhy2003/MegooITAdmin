import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { initialStep, LoginFlow } from "@/components/auth/login-flow";
import { ApiError, apiFetch } from "@/lib/api";
import type { AuthStatus } from "@/lib/auth/gate";
import { goTo } from "@/lib/auth/navigate";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), apiFetch: vi.fn() }));
vi.mock("@/lib/auth/navigate");

const ENROLMENT = { secret: "ABCDEFGHIJKLMNOP", uri: "otpauth://totp/MegooITAdmin:a%40b.c?secret=ABCDEFGHIJKLMNOP" };
const CODES = Array.from({ length: 10 }, (_, i) => `AAAA-BBBB-CCCC-000${i}`);

beforeEach(() => {
  vi.mocked(apiFetch).mockReset();
  vi.mocked(goTo).mockReset();
});

async function signIn(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText("Email"), "owner@example.com");
  await user.type(screen.getByLabelText("Password"), "correct horse battery");
  await user.click(screen.getByRole("button", { name: "Continue" }));
}

async function enterCode(user: ReturnType<typeof userEvent.setup>, label: string, code: string) {
  await user.type(await screen.findByLabelText(label), code);
  await user.click(screen.getByRole("button", { name: "Verify" }));
}

describe("initialStep", () => {
  it.each<[AuthStatus | undefined, string]>([
    ["mfa_required", "code"],
    ["enrolment_required", "enrol"],
    ["signed_out", "password"],
    ["setup_required", "password"],
    ["active", "password"],
    [undefined, "password"],
  ])("%s → %s", (status, step) => {
    expect(initialStep(status)).toBe(step);
  });
});

describe("LoginFlow", () => {
  it("goes from the password to the code, then to next", async () => {
    vi.mocked(apiFetch).mockResolvedValueOnce({ status: "mfa_required" }).mockResolvedValueOnce({ status: "active" });
    const user = userEvent.setup();
    render(<LoginFlow initialStep="password" next="/servers" />);

    await signIn(user);
    expect(await screen.findByText("Enter your code")).toBeInTheDocument();
    await enterCode(user, "Code", "123456");

    expect(goTo).toHaveBeenCalledWith("/servers");
  });

  it("enrols an authenticator, shows the recovery codes, then goes home", async () => {
    vi.mocked(apiFetch)
      .mockResolvedValueOnce({ status: "enrolment_required" })
      .mockResolvedValueOnce(ENROLMENT)
      .mockResolvedValueOnce({ status: "active", recovery_codes: CODES });
    const user = userEvent.setup();
    render(<LoginFlow initialStep="password" next={null} />);

    await signIn(user);
    expect(await screen.findByText("Set up your authenticator")).toBeInTheDocument();
    await enterCode(user, "Code", "123456");
    expect(await screen.findByText("Save your recovery codes")).toBeInTheDocument();
    expect(goTo).not.toHaveBeenCalled();
    await user.click(screen.getByLabelText("I have saved these codes"));
    await user.click(screen.getByRole("button", { name: "Continue" }));

    expect(goTo).toHaveBeenCalledWith("/");
  });

  it("goes on at once when the enrolment gives no recovery codes", async () => {
    vi.mocked(apiFetch).mockResolvedValueOnce(ENROLMENT).mockResolvedValueOnce({ status: "active", recovery_codes: null });
    const user = userEvent.setup();
    render(<LoginFlow initialStep="enrol" next="/audit" />);

    await enterCode(user, "Code", "123456");

    expect(goTo).toHaveBeenCalledWith("/audit");
  });

  it("shows the locked notice and goes back to the password", async () => {
    vi.mocked(apiFetch).mockRejectedValue(new ApiError(423, "locked"));
    const user = userEvent.setup();
    render(<LoginFlow initialStep="code" next={null} />);

    await enterCode(user, "Code", "000000");
    expect(await screen.findByText("Account locked")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Back to sign-in" }));

    expect(screen.getByText("Sign in")).toBeInTheDocument();
    expect(goTo).not.toHaveBeenCalled();
  });

  it("signs in with a recovery code", async () => {
    vi.mocked(apiFetch).mockResolvedValue({ status: "active" });
    const user = userEvent.setup();
    render(<LoginFlow initialStep="code" next="/servers" />);

    await user.click(screen.getByRole("button", { name: "Use a recovery code" }));
    await enterCode(user, "Recovery code", "AAAA-BBBB-CCCC-DDDD");

    expect(apiFetch).toHaveBeenCalledWith("/auth/login/mfa", {
      body: { code: "AAAA-BBBB-CCCC-DDDD", method: "recovery_code" },
    });
    expect(goTo).toHaveBeenCalledWith("/servers");
  });

  it("starts again with a notice when the sign-in has expired", async () => {
    vi.mocked(apiFetch).mockRejectedValue(new ApiError(401, "not_signed_in"));
    const user = userEvent.setup();
    render(<LoginFlow initialStep="code" next={null} />);

    await enterCode(user, "Code", "123456");

    expect(await screen.findByText("Sign in")).toBeInTheDocument();
    expect(screen.getByText("Your sign-in took too long. Start again.")).toBeInTheDocument();
  });
});
