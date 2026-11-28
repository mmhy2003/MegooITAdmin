import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useRouter, useSearchParams } from "next/navigation";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mockElementSize } from "@/__tests__/helpers/element-size";
import { FakeWebSocket, installFakeWebSocket } from "@/__tests__/helpers/fake-websocket";
import { server } from "@/components/dashboard/__tests__/fixtures";
import { LogsPage } from "@/components/logs/logs-page";
import { ApiError, apiFetch } from "@/lib/api";
import { messageFor } from "@/lib/auth/messages";
import { DEFAULT_SETTINGS, encodeSource, queryOf, wire, type LogSource, type ViewState } from "@/lib/logs/sources";
import { bodyOf, stateOf, type LogView } from "@/lib/logs/views";
import type { Server } from "@/lib/servers";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), apiFetch: vi.fn() }));
vi.mock("@/lib/auth/navigate");

const A = "6f1c2a8e-4b3d-4e5f-9a0b-1c2d3e4f5a6b";
const WEB_01 = server("web-01", null, { id: A, can_view_logs: true });
const JOURNAL: LogSource = { kind: "journal", server_id: A, unit: "nginx.service", priority: null, this_boot: false };

const MINE: LogView = {
  id: "v1",
  name: "Web errors",
  shared: false,
  owner_name: "Ada",
  is_mine: true,
  can_edit: true,
  sources: [JOURNAL],
  settings: DEFAULT_SETTINGS,
  updated_at: "2026-11-28T10:00:00Z",
};
const THEIRS: LogView = { ...MINE, id: "v2", name: "Nightly jobs", shared: true, owner_name: "Grace", is_mine: false,
  can_edit: false };

let replace: ReturnType<typeof vi.fn>;
let servers: Server[] | Error = [WEB_01];
let views: LogView[] = [];

function query(search: string) {
  vi.mocked(useSearchParams).mockReturnValue(
    new URLSearchParams(search) as unknown as ReturnType<typeof useSearchParams>,
  );
}

async function page() {
  const result = render(<LogsPage />);
  await act(async () => {});
  return result;
}

let restore: () => void;
beforeEach(() => {
  vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => {
    cb(0);
    return 0;
  });
  vi.stubGlobal("cancelAnimationFrame", () => {});
  installFakeWebSocket();
  restore = mockElementSize();
  servers = [WEB_01];
  replace = vi.fn();
  vi.mocked(useRouter).mockReturnValue({ push: vi.fn(), replace, refresh: vi.fn() } as unknown as ReturnType<
    typeof useRouter
  >);
  views = [];
  query("");
  vi.mocked(apiFetch).mockReset();
  vi.mocked(apiFetch).mockImplementation(async (path: string, init?: { method?: string }) => {
    if (path === "/servers") {
      if (servers instanceof Error) throw servers;
      return servers;
    }
    if (path === "/log-views" && !init) return views;
    if (path === "/log-views/v1" && init?.method === "PUT") return MINE;
    if (path === "/log-views/v1" && init?.method === "DELETE") {
      views = views.filter((v) => v.id !== "v1");
      return undefined;
    }
    throw new Error(`unexpected ${path}`);
  });
});
afterEach(() => {
  restore();
  vi.unstubAllGlobals();
});

describe("LogsPage", () => {
  it("says where View logs is granted when the person holds it on no server, and opens no socket", async () => {
    servers = [server("web-01", null, { id: A, can_view_logs: false })];
    query(new URLSearchParams({ src: encodeSource(JOURNAL) }).toString());
    await page();
    expect(
      screen.getByText("You do not hold View logs on any server. The Owner grants it in Settings → Users."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add source" })).not.toBeInTheDocument();
    expect(FakeWebSocket.instances).toHaveLength(0);
  });

  it("shows why the servers could not be read", async () => {
    servers = new ApiError(403, "forbidden");
    await page();
    expect(screen.getByRole("alert")).toHaveTextContent(messageFor("forbidden"));
    expect(FakeWebSocket.instances).toHaveLength(0);
  });

  it("offers to add a source when the address has none", async () => {
    await page();
    await userEvent.click(screen.getByRole("button", { name: "Add source" }));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText("A view holds at most 16 sources, 8 per server.")).toBeInTheDocument();
    expect(FakeWebSocket.instances).toHaveLength(0);
  });

  it("follows the sources of the address and writes each change back to it", async () => {
    query(new URLSearchParams({ src: encodeSource(JOURNAL), view: "v1" }).toString());
    await page();
    const ws = FakeWebSocket.instances[0];
    act(() => ws.open());
    expect(ws.sent).toEqual([{ type: "subscribe", sources: [wire(JOURNAL)] }]);

    await userEvent.click(screen.getByRole("button", { name: "Wrap" }));
    expect(replace).toHaveBeenLastCalledWith(`/logs?${new URLSearchParams({ src: encodeSource(JOURNAL), wrap: "1", view: "v1" })}`);
  });

  it("goes back to the bare address when the change leaves every default", async () => {
    query(`wrap=1`);
    await page();
    await userEvent.click(screen.getByRole("button", { name: "Wrap" }));
    expect(replace).toHaveBeenLastCalledWith("/logs");
  });

  describe("saved views", () => {
    const CHANGED: ViewState = { ...stateOf(MINE), settings: { ...DEFAULT_SETTINGS, wrap: true } };
    const listed = () => vi.mocked(apiFetch).mock.calls.filter(([path, init]) => path === "/log-views" && !init);

    async function menu() {
      await userEvent.click(screen.getByRole("button", { name: "Views" }));
      return (await screen.findAllByRole("menuitem")).map((item) => item.textContent);
    }

    it("says in the menu that the views could not be read, not that there are none", async () => {
      const answer = vi.mocked(apiFetch).getMockImplementation()!;
      vi.mocked(apiFetch).mockImplementation(async (path, init) => {
        if (path === "/log-views" && !init) throw new ApiError(500, "error");
        return answer(path, init);
      });
      await page();
      await menu();
      expect(screen.getByText("The saved views could not be read.")).toBeInTheDocument();
      expect(screen.queryByText("No saved views yet.")).not.toBeInTheDocument();
    });

    it("opens a view by writing its state and its id into the address", async () => {
      views = [MINE];
      await page();
      await menu();
      await userEvent.click(screen.getByRole("menuitem", { name: "Web errors" }));
      expect(replace).toHaveBeenLastCalledWith(`/logs?${queryOf(stateOf(MINE), "v1")}`);
    });

    it("names the open view, and says when the viewer differs from it", async () => {
      views = [MINE];
      query(queryOf(stateOf(MINE), "v1"));
      const { unmount } = await page();
      expect(screen.getByRole("heading", { name: "Web errors" })).toBeInTheDocument();
      expect(screen.queryByText("Changed")).not.toBeInTheDocument();
      unmount();

      query(queryOf(CHANGED, "v1"));
      await page();
      expect(screen.getByRole("heading", { name: "Web errors" })).toBeInTheDocument();
      expect(screen.getByText("Changed")).toBeInTheDocument();
    });

    it("saves what the viewer shows into the open view, then reads the views again", async () => {
      views = [MINE];
      query(queryOf(CHANGED, "v1"));
      await page();
      expect(listed()).toHaveLength(1);
      await menu();
      await userEvent.click(screen.getByRole("menuitem", { name: "Save" }));
      expect(apiFetch).toHaveBeenCalledWith("/log-views/v1", { method: "PUT", body: bodyOf(CHANGED, "Web errors", false) });
      expect(listed()).toHaveLength(2);
    });

    it("keeps a view saved as new in the address while the views are read again", async () => {
      const NEW: LogView = { ...MINE, id: "v9", name: "Edge", settings: CHANGED.settings };
      views = [];
      query(queryOf(CHANGED));
      let lists = 0;
      vi.mocked(apiFetch).mockImplementation(async (path: string, init?: { method?: string }) => {
        if (path === "/servers") return servers;
        // The first read answers, the one after the save never does: the list stays the one without the new view.
        if (path === "/log-views" && !init) return lists++ === 0 ? views : new Promise<never>(() => {});
        if (path === "/log-views" && init?.method === "POST") return NEW;
        throw new Error(`unexpected ${path}`);
      });
      const { rerender } = await page();
      await menu();
      await userEvent.click(screen.getByRole("menuitem", { name: "Save as a new view" }));
      await userEvent.type(screen.getByRole("textbox", { name: "Name" }), "Edge");
      await userEvent.click(screen.getByRole("button", { name: "Save view" }));
      expect(replace).toHaveBeenLastCalledWith(`/logs?${queryOf(CHANGED, "v9")}`);

      query(queryOf(CHANGED, "v9"));
      rerender(<LogsPage />);
      await act(async () => {});
      expect(replace).toHaveBeenLastCalledWith(`/logs?${queryOf(CHANGED, "v9")}`);
      expect(screen.getByRole("heading", { name: "Edge" })).toBeInTheDocument();
    });

    it("drops the view from the address once a reload no longer lists it", async () => {
      views = [MINE];
      query(queryOf(stateOf(MINE), "v1"));
      await page();
      await menu();
      await userEvent.click(screen.getByRole("menuitem", { name: "Delete…" }));
      await userEvent.click(screen.getByRole("button", { name: "Delete view" }));
      expect(apiFetch).toHaveBeenCalledWith("/log-views/v1", { method: "DELETE" });
      expect(replace).toHaveBeenLastCalledWith(`/logs?${queryOf(stateOf(MINE))}`);
    });

    it("offers the Owner to delete another person's shared view, and a reader not", async () => {
      views = [{ ...THEIRS, can_edit: true }];
      query(queryOf(stateOf(THEIRS), "v2"));
      const { unmount } = await page();
      expect(await menu()).toContain("Delete…");
      unmount();

      views = [THEIRS];
      await page();
      expect(await menu()).not.toContain("Delete…");
    });
  });
});
