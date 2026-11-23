import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { PasswordStep } from "@/components/auth/password-step";
import { ApiError, apiFetch } from "@/lib/api";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), apiFetch: vi.fn() }));
vi.mock("@/lib/auth/navigate");

beforeEach(() => {
  vi.mocked(apiFetch).mockReset();
});

async function signIn(email: string, password: string) {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Email"), email);
  await user.type(screen.getByLabelText("Password"), password);
  await user.click(screen.getByRole("button", { name: "Continue" }));
}

describe("PasswordStep", () => {
  it("posts the trimmed email and the password, then hands on the status", async () => {
    vi.mocked(apiFetch).mockResolvedValue({ status: "mfa_required" });
    const onDone = vi.fn();
    render(<PasswordStep onDone={onDone} />);
    expect(screen.getByText("Sign in")).toBeInTheDocument();

    await signIn("  owner@example.com ", "a long password");

    expect(apiFetch).toHaveBeenCalledWith("/auth/login", {
      body: { email: "owner@example.com", password: "a long password" },
    });
    expect(onDone).toHaveBeenCalledWith("mfa_required");
  });

  it("says when the email or the password is wrong", async () => {
    vi.mocked(apiFetch).mockRejectedValue(new ApiError(401, "invalid_credentials"));
    const onDone = vi.fn();
    render(<PasswordStep onDone={onDone} />);

    await signIn("owner@example.com", "wrong");

    expect(await screen.findByRole("alert")).toHaveTextContent("The email or the password is wrong.");
    expect(onDone).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Continue" })).toBeEnabled();
  });

  it("says when the server is not answering", async () => {
    vi.mocked(apiFetch).mockRejectedValue(new ApiError(0, "unreachable"));
    render(<PasswordStep onDone={vi.fn()} />);

    await signIn("owner@example.com", "a long password");

    expect(await screen.findByRole("alert")).toHaveTextContent("The server is not answering. Try again in a moment.");
  });

  it("shows the notice it is given", () => {
    render(<PasswordStep onDone={vi.fn()} notice="Your sign-in took too long. Start again." />);
    expect(screen.getByText("Your sign-in took too long. Start again.")).toBeInTheDocument();
  });

  it("disables Continue while the request runs", async () => {
    vi.mocked(apiFetch).mockReturnValue(new Promise(() => {}));
    render(<PasswordStep onDone={vi.fn()} />);

    await signIn("owner@example.com", "a long password");

    expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
  });
});
