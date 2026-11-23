import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { InviteFlow, InviteSignedIn } from "@/components/auth/invite-flow";
import { ApiError, apiFetch } from "@/lib/api";
import { goTo } from "@/lib/auth/navigate";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), apiFetch: vi.fn() }));
vi.mock("@/lib/auth/navigate");

const ENROLMENT = { secret: "ABCDEFGHIJKLMNOP", uri: "otpauth://totp/MegooITAdmin:ada%40example.com?secret=ABCDEFGHIJKLMNOP" };
const CODES = Array.from({ length: 10 }, (_, i) => `AAAA-BBBB-CCCC-000${i}`);
const PASSWORD = "correct horse battery";
const ADA = { name: "Ada Lovelace", email: "ada@example.com" };

beforeEach(() => {
  vi.mocked(apiFetch).mockReset();
  vi.mocked(goTo).mockReset();
});

afterEach(() => {
  window.history.replaceState(null, "", "/");
  vi.unstubAllGlobals();
});

function openLink(hash: string) {
  window.history.replaceState(null, "", `/invite${hash}`);
}

async function fill(user: ReturnType<typeof userEvent.setup>, password = PASSWORD, repeat = password) {
  await user.type(await screen.findByLabelText("Password"), password);
  await user.type(screen.getByLabelText("Repeat the password"), repeat);
  await user.click(screen.getByRole("button", { name: "Set password" }));
}

describe("InviteFlow", () => {
  it("checks a valid link and welcomes the person by name", async () => {
    openLink("#tok-123");
    vi.mocked(apiFetch).mockResolvedValueOnce(ADA);
    render(<InviteFlow />);

    expect(screen.getByText("Checking the invite link…")).toBeInTheDocument();
    expect(await screen.findByText("Welcome, Ada Lovelace")).toBeInTheDocument();
    expect(screen.getByText("ada@example.com")).toBeInTheDocument();
    expect(screen.getByText("Step 1 of 3")).toBeInTheDocument();
    expect(apiFetch).toHaveBeenCalledWith("/auth/invite/check", { body: { token: "tok-123" } });
  });

  it("says a link without a token does not work, and asks nothing", async () => {
    openLink("");
    render(<InviteFlow />);

    expect(await screen.findByText("This invite link does not work")).toBeInTheDocument();
    expect(screen.getByText("Ask the Owner for a new link.")).toBeInTheDocument();
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("says a refused link does not work", async () => {
    openLink("#tok-dead");
    vi.mocked(apiFetch).mockRejectedValueOnce(new ApiError(404, "invalid_invite"));
    render(<InviteFlow />);

    expect(await screen.findByText("This invite link does not work")).toBeInTheDocument();
    expect(screen.getByText("Ask the Owner for a new link.")).toBeInTheDocument();
    expect(screen.queryByLabelText("Password")).not.toBeInTheDocument();
  });

  it("posts nothing when the password is too short", async () => {
    openLink("#tok-123");
    vi.mocked(apiFetch).mockResolvedValueOnce(ADA);
    const user = userEvent.setup();
    render(<InviteFlow />);

    await fill(user, "short");

    expect(screen.getByRole("alert")).toHaveTextContent("Use 12 to 128 characters.");
    expect(apiFetch).toHaveBeenCalledTimes(1);
  });

  it("posts nothing when the passwords do not match", async () => {
    openLink("#tok-123");
    vi.mocked(apiFetch).mockResolvedValueOnce(ADA);
    const user = userEvent.setup();
    render(<InviteFlow />);

    await fill(user, PASSWORD, PASSWORD + "!");

    expect(screen.getByRole("alert")).toHaveTextContent("The passwords do not match.");
    expect(apiFetch).toHaveBeenCalledTimes(1);
  });

  it("shows why the link was refused when the password is set", async () => {
    openLink("#tok-123");
    vi.mocked(apiFetch).mockResolvedValueOnce(ADA).mockRejectedValueOnce(new ApiError(404, "invalid_invite"));
    const user = userEvent.setup();
    render(<InviteFlow />);

    await fill(user);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This invite link does not work. Ask the Owner for a new one.",
    );
    expect(screen.getByText("Step 1 of 3")).toBeInTheDocument();
  });

  it("sets the password, drops the token from the address, enrols, shows the codes and goes home", async () => {
    openLink("#tok-123");
    vi.mocked(apiFetch)
      .mockResolvedValueOnce(ADA)
      .mockResolvedValueOnce({ status: "enrolment_required" })
      .mockResolvedValueOnce(ENROLMENT)
      .mockResolvedValueOnce({ status: "active", recovery_codes: CODES });
    const user = userEvent.setup();
    render(<InviteFlow />);

    await fill(user);

    expect(apiFetch).toHaveBeenCalledWith("/auth/invite/accept", { body: { token: "tok-123", password: PASSWORD } });
    expect(await screen.findByText("Step 2 of 3")).toBeInTheDocument();
    expect(window.location.pathname).toBe("/invite");
    expect(window.location.hash).toBe("");
    await user.type(await screen.findByLabelText("Code"), "123456");
    await user.click(screen.getByRole("button", { name: "Verify" }));
    expect(await screen.findByText("Step 3 of 3")).toBeInTheDocument();
    await user.click(screen.getByLabelText("I have saved these codes"));
    await user.click(screen.getByRole("button", { name: "Continue" }));

    expect(goTo).toHaveBeenCalledWith("/");
  });
});

describe("InviteSignedIn", () => {
  it("says who is signed in, signs out and reloads the link", async () => {
    const reload = vi.fn();
    vi.stubGlobal("location", { ...window.location, reload });
    vi.mocked(apiFetch).mockResolvedValueOnce(undefined);
    const user = userEvent.setup();
    render(<InviteSignedIn name="Grace Hopper" email="grace@example.com" />);

    expect(
      screen.getByText("You are signed in as Grace Hopper (grace@example.com). Sign out first to use this invite link."),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Sign out" }));

    expect(apiFetch).toHaveBeenCalledWith("/auth/logout", { body: {} });
    expect(reload).toHaveBeenCalled();
  });
});
