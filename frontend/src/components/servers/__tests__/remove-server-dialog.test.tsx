import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { RemoveServerDialog } from "@/components/servers/remove-server-dialog";
import { ApiError, apiFetch } from "@/lib/api";
import type { Server } from "@/lib/servers";

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
  can_view_logs: false,
  metrics_interval_seconds: 5,
  monitoring: null,
};

beforeEach(() => {
  vi.mocked(apiFetch).mockReset();
});

function renderDialog(props: Partial<Parameters<typeof RemoveServerDialog>[0]> = {}) {
  const onRemoved = vi.fn();
  const onOpenChange = vi.fn();
  render(<RemoveServerDialog server={WEB} open onOpenChange={onOpenChange} onRemoved={onRemoved} {...props} />);
  return { onRemoved, onOpenChange, user: userEvent.setup() };
}

describe("RemoveServerDialog", () => {
  it("asks before removing the server", () => {
    renderDialog();

    expect(screen.getByRole("heading", { name: "Remove web-01?" })).toBeInTheDocument();
    expect(
      screen.getByText("It leaves the inventory for good. The audit log keeps its history."),
    ).toBeInTheDocument();
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("removes the server only after Remove server", async () => {
    vi.mocked(apiFetch).mockResolvedValue(undefined);
    const { user, onRemoved } = renderDialog();

    await user.click(screen.getByRole("button", { name: "Remove server" }));

    expect(apiFetch).toHaveBeenCalledWith("/servers/s-1", { method: "DELETE" });
    expect(onRemoved).toHaveBeenCalled();
  });

  it("closes on Cancel without removing", async () => {
    const { user, onOpenChange, onRemoved } = renderDialog();

    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(apiFetch).not.toHaveBeenCalled();
    expect(onRemoved).not.toHaveBeenCalled();
  });

  it("shows a refusal", async () => {
    vi.mocked(apiFetch).mockRejectedValue(new ApiError(403, "forbidden"));
    const { user, onRemoved } = renderDialog();

    await user.click(screen.getByRole("button", { name: "Remove server" }));

    expect(await screen.findByText("You do not have the rights to do this.")).toBeInTheDocument();
    expect(onRemoved).not.toHaveBeenCalled();
  });

  it("is closed without a server", () => {
    renderDialog({ server: null });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
