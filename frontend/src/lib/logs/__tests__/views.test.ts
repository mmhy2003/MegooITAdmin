import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiFetch } from "@/lib/api";
import { DEFAULT_SETTINGS, type LogSource, type ViewState } from "@/lib/logs/sources";
import {
  bodyOf,
  createView,
  deleteView,
  differs,
  type LogView,
  listViews,
  MAX_VIEW_NAME,
  stateOf,
  updateView,
  type ViewBody,
} from "@/lib/logs/views";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), apiFetch: vi.fn() }));
vi.mock("@/lib/auth/navigate");

const S = "6f1c2d3e-4a5b-4c6d-8e7f-901234567890";
const journal: LogSource = { kind: "journal", server_id: S, unit: "nginx.service", priority: "err", this_boot: true };
const container: LogSource = { kind: "container", server_id: S, container_id: "3f2a9b8c7d6e", name: "web" };

const view = (fields: Partial<LogView> = {}): LogView => ({
  id: "v-1",
  name: "Web",
  shared: false,
  owner_name: "Ada Admin",
  is_mine: true,
  can_edit: true,
  sources: [journal, container],
  settings: { ...DEFAULT_SETTINGS, q: "timeout" },
  updated_at: "2026-11-28T09:00:00Z",
  ...fields,
});
const state = (fields: Partial<ViewState> = {}): ViewState => ({
  sources: [journal, container],
  settings: { ...DEFAULT_SETTINGS, q: "timeout" },
  ...fields,
});
const body: ViewBody = { name: "Web", shared: true, sources: [], settings: DEFAULT_SETTINGS };

beforeEach(() => {
  vi.mocked(apiFetch).mockReset();
});

describe("listViews", () => {
  it("reads /log-views and drops a source that breaks a rule", async () => {
    vi.mocked(apiFetch).mockResolvedValue([
      view({
        sources: [
          { kind: "file", server_id: S, path: "/var/log/syslog" },
          { kind: "file", server_id: S, path: "/var/../etc/shadow" },
          { kind: "container", server_id: S.toUpperCase(), container_id: "3f2a9b8c7d6e" },
        ] as unknown as LogSource[],
      }),
    ]);

    const views = await listViews();

    expect(apiFetch).toHaveBeenCalledWith("/log-views");
    expect(views).toHaveLength(1);
    expect(views[0].sources).toEqual([
      { kind: "file", server_id: S, path: "/var/log/syslog" },
      { kind: "container", server_id: S, container_id: "3f2a9b8c7d6e", name: null },
    ]);
    expect(views[0].name).toBe("Web");
  });
});

describe("the changes", () => {
  it("creates a view with a POST", async () => {
    vi.mocked(apiFetch).mockResolvedValue(view());
    expect(await createView(body)).toEqual(view());
    expect(apiFetch).toHaveBeenCalledWith("/log-views", { method: "POST", body });
  });

  it("replaces a view with a PUT", async () => {
    vi.mocked(apiFetch).mockResolvedValue(view());
    await updateView("v-1", body);
    expect(apiFetch).toHaveBeenCalledWith("/log-views/v-1", { method: "PUT", body });
  });

  it("deletes a view with a DELETE", async () => {
    vi.mocked(apiFetch).mockResolvedValue(undefined);
    await deleteView("v-1");
    expect(apiFetch).toHaveBeenCalledWith("/log-views/v-1", { method: "DELETE" });
  });
});

describe("bodyOf", () => {
  it("keeps a container's name and puts the levels in order", () => {
    const settings = { ...DEFAULT_SETTINGS, levels: ["none", "error", "info"] as ViewState["settings"]["levels"] };
    expect(bodyOf(state({ settings }), "Web", true)).toEqual({
      name: "Web",
      shared: true,
      sources: [
        { kind: "journal", server_id: S, unit: "nginx.service", priority: "err", this_boot: true },
        { kind: "container", server_id: S, container_id: "3f2a9b8c7d6e", name: "web" },
      ],
      settings: { ...DEFAULT_SETTINGS, levels: ["error", "info", "none"] },
    });
  });
});

describe("stateOf", () => {
  it("gives the sources and the settings of a view", () => {
    expect(stateOf(view())).toEqual(state());
  });
});

describe("differs", () => {
  it("is false for the state of the view", () => {
    expect(differs(state(), view())).toBe(false);
  });

  it("is true after a changed filter", () => {
    expect(differs(state({ settings: { ...DEFAULT_SETTINGS, q: "refused" } }), view())).toBe(true);
  });

  it("is true after the sources changed order", () => {
    expect(differs(state({ sources: [container, journal] }), view())).toBe(true);
  });
});

it("allows names of 80 characters", () => {
  expect(MAX_VIEW_NAME).toBe(80);
});
