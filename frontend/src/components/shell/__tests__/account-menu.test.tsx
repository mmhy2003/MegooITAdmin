import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AccountMenu } from "@/components/shell/account-menu";
import { ApiError, apiFetch } from "@/lib/api";
import { goTo } from "@/lib/auth/navigate";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), apiFetch: vi.fn() }));
vi.mock("@/lib/auth/navigate");

beforeEach(() => {
  vi.mocked(apiFetch).mockReset();
  vi.mocked(goTo).mockReset();
});

async function openMenu() {
  const user = userEvent.setup();
  render(<AccountMenu user={{ name: "Olive Owner", email: "owner@example.com" }} />);
  await user.click(screen.getByRole("button", { name: "Account" }));
  return user;
}

describe("AccountMenu", () => {
  it("shows the signed-in person's name and email", async () => {
    await openMenu();
    expect(await screen.findByText("Olive Owner")).toBeInTheDocument();
    expect(screen.getByText("owner@example.com")).toBeInTheDocument();
    expect(screen.queryByText("Sign-in is not available yet")).toBeNull();
  });

  it("links Profile and security to /profile", async () => {
    await openMenu();
    const item = await screen.findByRole("menuitem", { name: "Profile and security" });
    expect(item).toHaveAttribute("href", "/profile");
    expect(item).not.toHaveAttribute("aria-disabled");
  });

  it("signs out and goes to the sign-in page", async () => {
    vi.mocked(apiFetch).mockResolvedValue(undefined);
    const user = await openMenu();
    await user.click(await screen.findByRole("menuitem", { name: "Sign out" }));
    await waitFor(() => expect(goTo).toHaveBeenCalledWith("/login"));
    expect(apiFetch).toHaveBeenCalledWith("/auth/logout", { method: "POST" });
  });

  it("still goes to the sign-in page when signing out fails", async () => {
    vi.mocked(apiFetch).mockRejectedValue(new ApiError(0, "unreachable"));
    const user = await openMenu();
    await user.click(await screen.findByRole("menuitem", { name: "Sign out" }));
    await waitFor(() => expect(goTo).toHaveBeenCalledWith("/login"));
    expect(apiFetch).toHaveBeenCalledWith("/auth/logout", { method: "POST" });
  });
});
