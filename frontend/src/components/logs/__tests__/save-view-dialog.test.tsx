import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SaveViewDialog } from "@/components/logs/save-view-dialog";
import { ApiError, apiFetch } from "@/lib/api";
import { messageFor } from "@/lib/auth/messages";
import { DEFAULT_SETTINGS, type ViewState } from "@/lib/logs/sources";
import { bodyOf, stateOf, type LogView } from "@/lib/logs/views";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), apiFetch: vi.fn() }));
vi.mock("@/lib/auth/navigate");

const A = "6f1c2a8e-4b3d-4e5f-9a0b-1c2d3e4f5a6b";
const STATE: ViewState = {
  sources: [
    { kind: "journal", server_id: A, unit: "nginx.service", priority: null, this_boot: false },
    { kind: "container", server_id: A, container_id: "abc123", name: "web" },
  ],
  settings: { ...DEFAULT_SETTINGS, q: "error", levels: ["warning", "error"] },
};
const VIEW: LogView = {
  id: "v1",
  name: "Web errors",
  shared: false,
  owner_name: "Ada",
  is_mine: true,
  can_edit: true,
  sources: [{ kind: "file", server_id: A, path: "/var/log/syslog" }],
  settings: DEFAULT_SETTINGS,
  updated_at: "2026-11-28T10:00:00Z",
};
const HINT = "People who hold View logs on every server of this view see it.";

beforeEach(() => {
  vi.mocked(apiFetch).mockReset();
});

function renderDialog(view: LogView | null = null) {
  const onSaved = vi.fn();
  render(<SaveViewDialog view={view} state={STATE} open onOpenChange={vi.fn()} onSaved={onSaved} />);
  return { onSaved, user: userEvent.setup() };
}

describe("SaveViewDialog", () => {
  it("saves what the viewer shows as a new view", async () => {
    const saved = { ...VIEW, id: "v9", name: "Edge" };
    vi.mocked(apiFetch).mockResolvedValue(saved);
    const { user, onSaved } = renderDialog();

    expect(screen.getByRole("heading", { name: "Save as a new view" })).toBeInTheDocument();
    await user.type(screen.getByRole("textbox", { name: "Name" }), "  Edge ");
    const shared = screen.getByRole("checkbox", { name: "Shared" });
    expect(shared).toHaveAccessibleDescription(HINT);
    await user.click(shared);
    await user.click(screen.getByRole("button", { name: "Save view" }));

    expect(apiFetch).toHaveBeenCalledWith("/log-views", { method: "POST", body: bodyOf(STATE, "Edge", true) });
    expect(onSaved).toHaveBeenCalledWith(saved);
  });

  it("renames or shares a view with what it saved, not what the viewer shows", async () => {
    vi.mocked(apiFetch).mockResolvedValue({ ...VIEW, name: "Syslog", shared: true });
    const { user, onSaved } = renderDialog(VIEW);

    expect(screen.getByRole("heading", { name: "Rename or share Web errors" })).toBeInTheDocument();
    const name = screen.getByRole("textbox", { name: "Name" });
    expect(name).toHaveValue("Web errors");
    expect(screen.getByRole("checkbox", { name: "Shared" })).not.toBeChecked();
    await user.clear(name);
    await user.type(name, "Syslog");
    await user.click(screen.getByRole("checkbox", { name: "Shared" }));
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(apiFetch).toHaveBeenCalledWith("/log-views/v1", {
      method: "PUT",
      body: bodyOf(stateOf(VIEW), "Syslog", true),
    });
    expect(onSaved).toHaveBeenCalled();
  });

  it("refuses a name over 80 characters without asking the server", async () => {
    const { user, onSaved } = renderDialog();
    await user.type(screen.getByRole("textbox", { name: "Name" }), "x".repeat(81));
    await user.click(screen.getByRole("button", { name: "Save view" }));

    expect(screen.getByRole("alert")).toHaveTextContent("A name has at most 80 characters.");
    expect(apiFetch).not.toHaveBeenCalled();
    expect(onSaved).not.toHaveBeenCalled();
  });

  it.each(["view_name_taken", "too_many_views"])("says why the server refused: %s", async (reason) => {
    vi.mocked(apiFetch).mockRejectedValue(new ApiError(409, reason));
    const { user, onSaved } = renderDialog();
    await user.type(screen.getByRole("textbox", { name: "Name" }), "Edge");
    await user.click(screen.getByRole("button", { name: "Save view" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(messageFor(reason));
    expect(onSaved).not.toHaveBeenCalled();
  });
});
