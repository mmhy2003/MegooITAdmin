import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { PlatformAccessCard } from "@/components/servers/platform-access-card";
import { ApiError, apiFetch } from "@/lib/api";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), apiFetch: vi.fn() }));
vi.mock("@/lib/auth/navigate");

const KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGx0ZXN0a2V5Zm9ydGhlcGxhdGZvcm1hY2Nlc3NjYXJk megooitadmin";

beforeEach(() => {
  vi.mocked(apiFetch).mockReset();
});

describe("PlatformAccessCard", () => {
  it("shows both steps and the platform's public key", async () => {
    vi.mocked(apiFetch).mockResolvedValue({ public_key: KEY });
    render(<PlatformAccessCard username="megoo" />);

    expect(screen.getByRole("heading", { name: "Platform access" })).toBeInTheDocument();
    expect(
      screen.getByText("1. On the server, create the account megoo: not root, not in the docker group."),
    ).toBeInTheDocument();
    expect(screen.getByText("2. Add this public key to its ~/.ssh/authorized_keys:")).toBeInTheDocument();
    expect(await screen.findByText(KEY)).toBeInTheDocument();
    expect(apiFetch).toHaveBeenCalledWith("/ssh/public-key");
  });

  it("copies the key", async () => {
    const user = userEvent.setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    vi.mocked(apiFetch).mockResolvedValue({ public_key: KEY });
    render(<PlatformAccessCard username="megoo" />);
    await screen.findByText(KEY);

    await user.click(screen.getByRole("button", { name: "Copy" }));

    expect(writeText).toHaveBeenCalledWith(KEY);
    expect(await screen.findByRole("button", { name: "Copied" })).toBeInTheDocument();
  });

  it("says why the key could not be loaded", async () => {
    vi.mocked(apiFetch).mockRejectedValue(new ApiError(500, "error"));
    render(<PlatformAccessCard username="megoo" />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Something went wrong. Try again.");
    expect(screen.queryByRole("button", { name: "Copy" })).not.toBeInTheDocument();
  });
});
