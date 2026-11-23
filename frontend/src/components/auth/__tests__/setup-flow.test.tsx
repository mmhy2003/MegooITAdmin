import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SetupFlow } from "@/components/auth/setup-flow";
import { ApiError, apiFetch } from "@/lib/api";
import { goTo } from "@/lib/auth/navigate";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), apiFetch: vi.fn() }));
vi.mock("@/lib/auth/navigate");

const ENROLMENT = { secret: "ABCDEFGHIJKLMNOP", uri: "otpauth://totp/MegooITAdmin:a%40b.c?secret=ABCDEFGHIJKLMNOP" };
const CODES = Array.from({ length: 10 }, (_, i) => `AAAA-BBBB-CCCC-000${i}`);
const PASSWORD = "correct horse battery";

beforeEach(() => {
  vi.mocked(apiFetch).mockReset();
  vi.mocked(goTo).mockReset();
});

async function fill(user: ReturnType<typeof userEvent.setup>, password = PASSWORD, repeat = password) {
  await user.type(screen.getByLabelText("Setup code"), "ABCD-EFGH");
  await user.type(screen.getByLabelText("Your name"), "Ada Owner");
  await user.type(screen.getByLabelText("Email"), "owner@example.com");
  await user.type(screen.getByLabelText("Password"), password);
  await user.type(screen.getByLabelText("Repeat the password"), repeat);
  await user.click(screen.getByRole("button", { name: "Create the Owner account" }));
}

describe("SetupFlow", () => {
  it("shows the first step with its hints", () => {
    render(<SetupFlow />);

    expect(screen.getByText("Step 1 of 3")).toBeInTheDocument();
    expect(screen.getByText("Set up MegooITAdmin")).toBeInTheDocument();
    expect(screen.getByText("Run make setup-code on the host, or look for it in the backend's log.")).toBeInTheDocument();
    expect(screen.getByText("12 to 128 characters.")).toBeInTheDocument();
  });

  it("posts nothing when the password is too short", async () => {
    const user = userEvent.setup();
    render(<SetupFlow />);

    await fill(user, "short");

    expect(screen.getByRole("alert")).toHaveTextContent("Use 12 to 128 characters.");
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("posts nothing when the passwords do not match", async () => {
    const user = userEvent.setup();
    render(<SetupFlow />);

    await fill(user, PASSWORD, PASSWORD + "!");

    expect(screen.getByRole("alert")).toHaveTextContent("The passwords do not match.");
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("creates the Owner, enrols the authenticator, shows the codes and goes home", async () => {
    vi.mocked(apiFetch)
      .mockResolvedValueOnce({ status: "enrolment_required" })
      .mockResolvedValueOnce(ENROLMENT)
      .mockResolvedValueOnce({ status: "active", recovery_codes: CODES });
    const user = userEvent.setup();
    render(<SetupFlow />);

    await fill(user);

    expect(apiFetch).toHaveBeenCalledWith("/auth/setup", {
      body: { code: "ABCD-EFGH", name: "Ada Owner", email: "owner@example.com", password: PASSWORD },
    });
    expect(await screen.findByText("Step 2 of 3")).toBeInTheDocument();
    await user.type(await screen.findByLabelText("Code"), "123456");
    await user.click(screen.getByRole("button", { name: "Verify" }));
    expect(await screen.findByText("Step 3 of 3")).toBeInTheDocument();
    await user.click(screen.getByLabelText("I have saved these codes"));
    await user.click(screen.getByRole("button", { name: "Continue" }));

    expect(goTo).toHaveBeenCalledWith("/");
  });

  it("goes to sign-in when the install is already set up", async () => {
    vi.mocked(apiFetch).mockRejectedValue(new ApiError(409, "already_set_up"));
    const user = userEvent.setup();
    render(<SetupFlow />);

    await fill(user);

    expect(goTo).toHaveBeenCalledWith("/login");
  });

  it("says when the setup code is wrong", async () => {
    vi.mocked(apiFetch).mockRejectedValue(new ApiError(400, "wrong_setup_code"));
    const user = userEvent.setup();
    render(<SetupFlow />);

    await fill(user);

    expect(await screen.findByRole("alert")).toHaveTextContent("The setup code is not right.");
    expect(goTo).not.toHaveBeenCalled();
  });
});
