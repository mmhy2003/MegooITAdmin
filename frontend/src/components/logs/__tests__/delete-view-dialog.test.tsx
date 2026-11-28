import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DeleteViewDialog } from "@/components/logs/delete-view-dialog";
import { ApiError, apiFetch } from "@/lib/api";
import { messageFor } from "@/lib/auth/messages";
import { DEFAULT_SETTINGS } from "@/lib/logs/sources";
import type { LogView } from "@/lib/logs/views";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), apiFetch: vi.fn() }));
vi.mock("@/lib/auth/navigate");

const VIEW: LogView = {
  id: "v1",
  name: "Web errors",
  shared: true,
  owner_name: "Ada",
  is_mine: true,
  can_edit: true,
  sources: [{ kind: "file", server_id: "s1", path: "/var/log/syslog" }],
  settings: DEFAULT_SETTINGS,
  updated_at: "2026-11-28T10:00:00Z",
};

beforeEach(() => {
  vi.mocked(apiFetch).mockReset();
});

describe("DeleteViewDialog", () => {
  it("deletes the view once confirmed", async () => {
    vi.mocked(apiFetch).mockResolvedValue(undefined);
    const onDeleted = vi.fn();
    render(<DeleteViewDialog view={VIEW} open onOpenChange={vi.fn()} onDeleted={onDeleted} />);

    expect(screen.getByRole("heading", { name: "Delete Web errors?" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Delete view" }));

    expect(apiFetch).toHaveBeenCalledWith("/log-views/v1", { method: "DELETE" });
    expect(onDeleted).toHaveBeenCalled();
  });

  it("says why the view could not be deleted", async () => {
    vi.mocked(apiFetch).mockRejectedValue(new ApiError(404, "not_found"));
    const onDeleted = vi.fn();
    render(<DeleteViewDialog view={VIEW} open onOpenChange={vi.fn()} onDeleted={onDeleted} />);
    await userEvent.click(screen.getByRole("button", { name: "Delete view" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(messageFor("not_found"));
    expect(onDeleted).not.toHaveBeenCalled();
  });
});
