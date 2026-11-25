import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { HostKeyDialog } from "@/components/servers/host-key-dialog";
import { ApiError, apiFetch } from "@/lib/api";
import type { HostKeyFetchResult, Server } from "@/lib/servers";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), apiFetch: vi.fn() }));
vi.mock("@/lib/auth/navigate");

const WEB: Server = {
  id: "s-1",
  name: "web-01",
  address: "10.0.0.5",
  port: 22,
  os: "linux",
  role: "web",
  tags: ["nginx"],
  group_id: "g-staging",
  group_name: "staging",
  connection_settings: { username: "megoo" },
  host_key: null,
  created_at: "2026-11-01T00:00:00Z",
  updated_at: "2026-11-01T00:00:00Z",
  can_manage: true,
  host_key_state: "not_pinned",
  host_key_fingerprint: null,
  host_key_type: null,
  host_key_pinned_at: null,
  host_key_changed_at: null,
  host_key_offered: null,
  can_connect: true,
  metrics_interval_seconds: 5,
  monitoring: null,
};

const FINGERPRINT = "SHA256:abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG";
const FETCHED: HostKeyFetchResult = { ok: true, reason: null, fingerprint: FINGERPRINT, type: "ssh-ed25519" };
const PINNED: Server = { ...WEB, host_key_state: "pinned", host_key_fingerprint: FINGERPRINT, host_key_type: "ssh-ed25519" };
const FETCH = ["/servers/s-1/host-key/fetch", { method: "POST" }];

beforeEach(() => {
  vi.mocked(apiFetch).mockReset();
});

function renderDialog() {
  const onPinned = vi.fn();
  const onStale = vi.fn();
  const onOpenChange = vi.fn();
  render(<HostKeyDialog server={WEB} open onOpenChange={onOpenChange} onPinned={onPinned} onStale={onStale} />);
  return { onPinned, onStale, onOpenChange, user: userEvent.setup() };
}

describe("HostKeyDialog", () => {
  it("fetches the server's key when it opens and shows how to compare it", async () => {
    vi.mocked(apiFetch).mockResolvedValue(FETCHED);
    renderDialog();

    expect(screen.getByRole("heading", { name: "Pin the host key of web-01" })).toBeInTheDocument();
    expect(screen.getByText("Fetching the server's key…")).toBeInTheDocument();
    expect(await screen.findByText(FINGERPRINT)).toBeInTheDocument();
    expect(apiFetch).toHaveBeenCalledWith(...FETCH);
    expect(screen.getByText("Fingerprint")).toBeInTheDocument();
    expect(screen.getByText("Type")).toBeInTheDocument();
    expect(screen.getByText("ssh-ed25519")).toBeInTheDocument();
    expect(screen.getByText("Compare it on the server, from a console you trust:")).toBeInTheDocument();
    expect(screen.getByText("ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub")).toBeInTheDocument();
  });

  it("pins the key only after the fingerprint is compared", async () => {
    vi.mocked(apiFetch).mockResolvedValueOnce(FETCHED).mockResolvedValueOnce(PINNED);
    const { user, onPinned } = renderDialog();

    const pin = await screen.findByRole("button", { name: "Pin this key" });
    expect(pin).toBeDisabled();
    await user.click(screen.getByRole("checkbox", { name: "I compared the fingerprint and it matches" }));
    expect(pin).toBeEnabled();
    await user.click(pin);

    expect(apiFetch).toHaveBeenLastCalledWith("/servers/s-1/host-key", {
      method: "PUT",
      body: { fingerprint: FINGERPRINT },
    });
    expect(onPinned).toHaveBeenCalledWith(PINNED);
  });

  it("shows why a fetch failed and tries again", async () => {
    vi.mocked(apiFetch)
      .mockResolvedValueOnce({ ok: false, reason: "unreachable", fingerprint: null, type: null })
      .mockResolvedValueOnce(FETCHED);
    const { user } = renderDialog();

    expect(await screen.findByText("The server did not answer.")).toBeInTheDocument();
    expect(
      screen.getByText("Check the address and the port, and that the server accepts SSH connections from MegooITAdmin."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Pin this key" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Try again" }));

    expect(await screen.findByText(FINGERPRINT)).toBeInTheDocument();
    expect(apiFetch).toHaveBeenCalledTimes(2);
    expect(apiFetch).toHaveBeenNthCalledWith(2, ...FETCH);
  });

  it("fetches the key again when it changed since it was compared", async () => {
    const newer = "SHA256:ZYXWVUTSRQPONMLKJIHGFEDCBA9876543210zyxwvut";
    vi.mocked(apiFetch)
      .mockResolvedValueOnce(FETCHED)
      .mockRejectedValueOnce(new ApiError(409, "stale_host_key"))
      .mockResolvedValueOnce({ ...FETCHED, fingerprint: newer });
    const { user, onPinned, onStale } = renderDialog();

    await user.click(await screen.findByRole("checkbox", { name: "I compared the fingerprint and it matches" }));
    await user.click(screen.getByRole("button", { name: "Pin this key" }));

    expect(
      await screen.findByText(
        "The server's key is no longer the one you compared. It has been fetched again: compare the new fingerprint.",
      ),
    ).toBeInTheDocument();
    expect(await screen.findByText(newer)).toBeInTheDocument();
    expect(apiFetch).toHaveBeenNthCalledWith(3, ...FETCH);
    expect(screen.getByRole("button", { name: "Pin this key" })).toBeDisabled();
    expect(onPinned).not.toHaveBeenCalled();
    expect(onStale).not.toHaveBeenCalled();
  });

  it.each([
    [403, "forbidden", "You do not have the rights to do this."],
    [409, "host_key_pinned", "A host key is pinned already. The page has been reloaded."],
  ])("shows a %i %s refusal and reloads the page", async (status, detail, text) => {
    vi.mocked(apiFetch).mockResolvedValueOnce(FETCHED).mockRejectedValueOnce(new ApiError(status, detail));
    const { user, onPinned, onStale } = renderDialog();

    await user.click(await screen.findByRole("checkbox", { name: "I compared the fingerprint and it matches" }));
    await user.click(screen.getByRole("button", { name: "Pin this key" }));

    expect(await screen.findByText(text)).toBeInTheDocument();
    expect(onStale).toHaveBeenCalled();
    expect(onPinned).not.toHaveBeenCalled();
    expect(apiFetch).toHaveBeenCalledTimes(2);
  });

  it("shows a refused fetch and reloads the page", async () => {
    vi.mocked(apiFetch).mockRejectedValueOnce(new ApiError(404, "not_found"));
    const { onStale } = renderDialog();

    expect(await screen.findByText("It does not exist, or you cannot see it.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Try again" })).not.toBeInTheDocument();
    expect(onStale).toHaveBeenCalled();
  });

  it("closes on Cancel without pinning", async () => {
    vi.mocked(apiFetch).mockResolvedValue(FETCHED);
    const { user, onOpenChange, onPinned } = renderDialog();

    await screen.findByText(FINGERPRINT);
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(apiFetch).toHaveBeenCalledTimes(1);
    expect(onPinned).not.toHaveBeenCalled();
  });
});
