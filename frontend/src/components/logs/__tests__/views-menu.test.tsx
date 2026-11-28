import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ViewsMenu } from "@/components/logs/views-menu";
import { DEFAULT_SETTINGS } from "@/lib/logs/sources";
import type { LogView } from "@/lib/logs/views";

const A = "6f1c2a8e-4b3d-4e5f-9a0b-1c2d3e4f5a6b";

function view(id: string, name: string, extra: Partial<LogView> = {}): LogView {
  return {
    id,
    name,
    shared: false,
    owner_name: "Ada",
    is_mine: true,
    can_edit: true,
    sources: [{ kind: "journal", server_id: A, unit: "nginx.service", priority: null, this_boot: false }],
    settings: DEFAULT_SETTINGS,
    updated_at: "2026-11-28T10:00:00Z",
    ...extra,
  };
}

const MINE = view("v1", "Web errors");
const THEIRS = view("v2", "Nightly jobs", { shared: true, owner_name: "Grace", is_mine: false, can_edit: false });

function renderMenu(props: Partial<Parameters<typeof ViewsMenu>[0]> = {}) {
  const handlers = { onOpen: vi.fn(), onSave: vi.fn(), onSaveAs: vi.fn(), onEdit: vi.fn(), onDelete: vi.fn() };
  render(<ViewsMenu views={[MINE, THEIRS]} current={null} changed={false} {...handlers} {...props} />);
  return { ...handlers, user: userEvent.setup() };
}

async function open(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: "Views" }));
  return (await screen.findAllByRole("menuitem")).map((item) => item.textContent);
}

describe("ViewsMenu", () => {
  it("lists the person's views and those shared with them, with the owner's name", async () => {
    const { user } = renderMenu();
    await open(user);
    expect(screen.getByText("My views")).toBeInTheDocument();
    expect(screen.getByText("Shared with me")).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Web errors" })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Nightly jobs Grace" })).toBeInTheDocument();
  });

  it("opens the view chosen", async () => {
    const { user, onOpen } = renderMenu();
    await open(user);
    await user.click(screen.getByRole("menuitem", { name: "Nightly jobs Grace" }));
    expect(onOpen).toHaveBeenCalledWith(THEIRS);
  });

  it("offers only to save as a new view without a current view", async () => {
    const { user, onSaveAs } = renderMenu();
    const items = await open(user);
    expect(items).not.toContain("Save");
    expect(items).not.toContain("Rename or share…");
    expect(items).not.toContain("Delete…");
    await user.click(screen.getByRole("menuitem", { name: "Save as a new view" }));
    expect(onSaveAs).toHaveBeenCalled();
  });

  it("offers Save only once a view the person may change differs from what is saved", async () => {
    const { user, onSave } = renderMenu({ current: MINE, changed: true });
    await user.click(screen.getByRole("button", { name: "Views" }));
    await user.click(await screen.findByRole("menuitem", { name: "Save" }));
    expect(onSave).toHaveBeenCalled();
  });

  it("does not offer Save for an unchanged view", async () => {
    const { user } = renderMenu({ current: MINE });
    const items = await open(user);
    expect(items).not.toContain("Save");
    expect(items).toContain("Save as a new view");
  });

  it("offers to rename, share and delete a view the person may change", async () => {
    const { user, onEdit, onDelete } = renderMenu({ current: MINE });
    await open(user);
    await user.click(screen.getByRole("menuitem", { name: "Rename or share…" }));
    expect(onEdit).toHaveBeenCalled();
    await open(user);
    await user.click(screen.getByRole("menuitem", { name: "Delete…" }));
    expect(onDelete).toHaveBeenCalled();
  });

  it("offers only to save as a new view for a view the person may not change", async () => {
    const { user } = renderMenu({ current: THEIRS, changed: true });
    const items = await open(user);
    expect(items).not.toContain("Save");
    expect(items).not.toContain("Rename or share…");
    expect(items).not.toContain("Delete…");
    expect(items).toContain("Save as a new view");
  });
});
