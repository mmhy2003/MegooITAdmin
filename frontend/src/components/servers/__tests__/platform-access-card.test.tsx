import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { PlatformAccessCard } from "@/components/servers/platform-access-card";
import { ApiError, apiFetch } from "@/lib/api";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), apiFetch: vi.fn() }));
vi.mock("@/lib/auth/navigate");

const KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGx0ZXN0a2V5Zm9ydGhlcGxhdGZvcm1hY2Nlc3NjYXJk megooitadmin";
const COMMAND = `sudo sh megoo-setup.sh --from '<platform-address>' --key '${KEY}'`;

beforeEach(() => {
  vi.mocked(apiFetch).mockReset();
});

describe("PlatformAccessCard", () => {
  it("gives the script", async () => {
    vi.mocked(apiFetch).mockResolvedValue({ public_key: KEY });
    render(<PlatformAccessCard username="megoo" />);

    expect(screen.getByRole("heading", { name: "Platform access" })).toBeInTheDocument();
    expect(screen.getByText("1. Get the setup script:")).toBeInTheDocument();
    const link = screen.getByRole("link", { name: "Download megoo-setup.sh" });
    expect(link).toHaveAttribute("href", "/api/ssh/setup-script");
    expect(link).toHaveAttribute("download");
    expect(screen.getByText("or take backend/app/ssh/megoo-setup.sh from the repository.")).toBeInTheDocument();
    await screen.findByText(COMMAND);
  });

  it("shows the command with the key", async () => {
    vi.mocked(apiFetch).mockResolvedValue({ public_key: KEY });
    render(<PlatformAccessCard username="megoo" />);

    expect(
      screen.getByText("2. Run it as root on the server, with the platform's address in place of <platform-address>:"),
    ).toBeInTheDocument();
    const code = await screen.findByText(COMMAND);
    expect(code.tagName).toBe("CODE");
    expect(code.textContent).toBe(COMMAND);
    expect(apiFetch).toHaveBeenCalledWith("/ssh/public-key");
  });

  it("adds --user only for another account", async () => {
    vi.mocked(apiFetch).mockResolvedValue({ public_key: KEY });
    const { unmount } = render(<PlatformAccessCard username="ops-bot" />);
    expect(await screen.findByText(`${COMMAND} --user 'ops-bot'`)).toBeInTheDocument();
    unmount();

    render(<PlatformAccessCard username="o'x" />);
    expect(await screen.findByText(`${COMMAND} --user 'o'\\''x'`)).toBeInTheDocument();
  });

  it("leaves --user out for megoo", async () => {
    vi.mocked(apiFetch).mockResolvedValue({ public_key: KEY });
    render(<PlatformAccessCard username="megoo" />);

    const code = await screen.findByText(COMMAND);
    expect(code.textContent).not.toContain("--user");
  });

  it("copies the command", async () => {
    const user = userEvent.setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    vi.mocked(apiFetch).mockResolvedValue({ public_key: KEY });
    render(<PlatformAccessCard username="ops-bot" />);
    await screen.findByText(`${COMMAND} --user 'ops-bot'`);

    await user.click(screen.getByRole("button", { name: "Copy" }));

    expect(writeText).toHaveBeenCalledWith(`${COMMAND} --user 'ops-bot'`);
    expect(await screen.findByRole("button", { name: "Copied" })).toBeInTheDocument();
  });

  it("shows step 3 and the firewall note", async () => {
    vi.mocked(apiFetch).mockResolvedValue({ public_key: KEY });
    render(<PlatformAccessCard username="megoo" />);

    expect(screen.getByText("3. Pin the host key and test the connection on this page.")).toBeInTheDocument();
    expect(
      screen.getByText(
        "The script accepts the key only from that address. Limit SSH (port 22) to it in the firewall too: see docs/server-setup.md.",
      ),
    ).toBeInTheDocument();
    await screen.findByText(COMMAND);
  });

  it("says why the key could not be loaded", async () => {
    vi.mocked(apiFetch).mockRejectedValue(new ApiError(500, "error"));
    render(<PlatformAccessCard username="megoo" />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Something went wrong. Try again.");
    expect(screen.queryByRole("button", { name: "Copy" })).not.toBeInTheDocument();
    expect(screen.queryByText(/sudo sh megoo-setup\.sh/)).not.toBeInTheDocument();
  });
});
