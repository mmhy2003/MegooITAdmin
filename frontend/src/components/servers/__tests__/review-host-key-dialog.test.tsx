import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ReviewHostKeyDialog } from "@/components/servers/review-host-key-dialog";
import { ApiError, apiFetch } from "@/lib/api";
import type { Server } from "@/lib/servers";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), apiFetch: vi.fn() }));
vi.mock("@/lib/auth/navigate");

const PINNED_KEY = "SHA256:abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG";
const OFFERED_KEY = "SHA256:ZYXWVUTSRQPONMLKJIHGFEDCBA9876543210zyxwvut";

const CHANGED: Server = {
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
  host_key_state: "changed",
  host_key_fingerprint: PINNED_KEY,
  host_key_type: "ssh-ed25519",
  host_key_pinned_at: "2026-11-02T00:00:00Z",
  host_key_changed_at: "2026-11-03T00:00:00Z",
  host_key_offered: { fingerprint: OFFERED_KEY, type: "ssh-ed25519", at: "2026-11-03T00:00:00Z" },
  can_connect: true,
};
const UNREAD: Server = { ...CHANGED, host_key_offered: null };
const REVIEWED: Server = { ...CHANGED, host_key_state: "pinned", host_key_changed_at: null, host_key_offered: null };

beforeEach(() => {
  vi.mocked(apiFetch).mockReset();
});

function renderDialog(server: Server = CHANGED) {
  const onDone = vi.fn();
  const onStale = vi.fn();
  const onOpenChange = vi.fn();
  render(<ReviewHostKeyDialog server={server} open onOpenChange={onOpenChange} onDone={onDone} onStale={onStale} />);
  return { onDone, onStale, onOpenChange, user: userEvent.setup() };
}

describe("ReviewHostKeyDialog", () => {
  it("shows the pinned key and the presented one", () => {
    renderDialog();

    expect(screen.getByRole("heading", { name: "Review the host key of web-01" })).toBeInTheDocument();
    expect(screen.getByText("Pinned key")).toBeInTheDocument();
    expect(screen.getByText(PINNED_KEY)).toBeInTheDocument();
    expect(screen.getByText("Presented key")).toBeInTheDocument();
    expect(screen.getByText(OFFERED_KEY)).toBeInTheDocument();
  });

  it("accepts the new key only with a reason", async () => {
    vi.mocked(apiFetch).mockResolvedValue(REVIEWED);
    const { user, onDone } = renderDialog();

    const accept = screen.getByRole("button", { name: "Accept the new key" });
    expect(accept).toBeDisabled();
    const reason = screen.getByLabelText("Why you accept the new key");
    await user.type(reason, "   ");
    expect(accept).toBeDisabled();
    await user.clear(reason);
    await user.type(reason, "Reinstalled on Monday");
    expect(accept).toBeEnabled();
    await user.click(accept);

    expect(apiFetch).toHaveBeenCalledWith("/servers/s-1/host-key", {
      method: "PUT",
      body: { fingerprint: OFFERED_KEY, reason: "Reinstalled on Monday" },
    });
    expect(onDone).toHaveBeenCalledWith(REVIEWED);
  });

  it("keeps the pinned key without a reason", async () => {
    vi.mocked(apiFetch).mockResolvedValue(REVIEWED);
    const { user, onDone } = renderDialog();

    await user.click(screen.getByRole("button", { name: "Keep the pinned key" }));

    expect(apiFetch).toHaveBeenCalledWith("/servers/s-1/host-key/keep", { method: "POST" });
    expect(onDone).toHaveBeenCalledWith(REVIEWED);
  });

  it("offers only to keep the pinned key when the presented one could not be read", () => {
    renderDialog(UNREAD);

    expect(screen.getByText("Could not be read")).toBeInTheDocument();
    expect(screen.getByText(PINNED_KEY)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Accept the new key" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Why you accept the new key")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Keep the pinned key" })).toBeEnabled();
  });

  it.each([
    [404, "not_found", "It does not exist, or you cannot see it."],
    [403, "forbidden", "You do not have the rights to do this."],
    [409, "host_key_not_changed", "This server's host key has not changed. The page has been reloaded."],
  ])("shows a %i %s refusal and reloads the page", async (status, detail, text) => {
    vi.mocked(apiFetch).mockRejectedValue(new ApiError(status, detail));
    const { user, onDone, onStale } = renderDialog();

    await user.click(screen.getByRole("button", { name: "Keep the pinned key" }));

    expect(await screen.findByText(text)).toBeInTheDocument();
    expect(onStale).toHaveBeenCalled();
    expect(onDone).not.toHaveBeenCalled();
  });

  it("shows a refusal that needs no reload and stays open", async () => {
    vi.mocked(apiFetch).mockRejectedValue(new ApiError(422, "reason_required"));
    const { user, onDone, onStale } = renderDialog();

    await user.type(screen.getByLabelText("Why you accept the new key"), "Reinstalled");
    await user.click(screen.getByRole("button", { name: "Accept the new key" }));

    expect(await screen.findByText("Say why you accept the new key.")).toBeInTheDocument();
    expect(onStale).not.toHaveBeenCalled();
    expect(onDone).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Accept the new key" })).toBeEnabled();
  });

  it("closes on Cancel without a review", async () => {
    const { user, onOpenChange } = renderDialog();

    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(apiFetch).not.toHaveBeenCalled();
  });
});
