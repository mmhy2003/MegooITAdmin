import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useRouter, useSearchParams } from "next/navigation";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mockElementSize } from "@/__tests__/helpers/element-size";
import { FakeWebSocket, installFakeWebSocket } from "@/__tests__/helpers/fake-websocket";
import { server } from "@/components/dashboard/__tests__/fixtures";
import ServerLogsTabDefault, { ServerLogsTab } from "@/components/logs/server-logs-tab";
import { apiFetch } from "@/lib/api";
import { DEFAULT_SETTINGS, encodeSource, queryOf, wire, type LogSource } from "@/lib/logs/sources";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), apiFetch: vi.fn() }));
vi.mock("@/lib/auth/navigate");

const A = "6f1c2a8e-4b3d-4e5f-9a0b-1c2d3e4f5a6b";
const B = "7a2d3b9f-5c4e-4f60-8b1c-2d3e4f5a6b7c";
const WEB_01 = server("web-01", null, { id: A, can_view_logs: true });
const HERE: LogSource = { kind: "journal", server_id: A, unit: "nginx.service", priority: null, this_boot: false };
const ELSEWHERE: LogSource = { kind: "journal", server_id: B, unit: null, priority: null, this_boot: false };

let replace: ReturnType<typeof vi.fn>;

function query(search: string) {
  vi.mocked(useSearchParams).mockReturnValue(
    new URLSearchParams(search) as unknown as ReturnType<typeof useSearchParams>,
  );
}

async function tab() {
  const result = render(<ServerLogsTab server={WEB_01} />);
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
  replace = vi.fn();
  vi.mocked(useRouter).mockReturnValue({ push: vi.fn(), replace, refresh: vi.fn() } as unknown as ReturnType<
    typeof useRouter
  >);
  query("tab=logs");
  vi.mocked(apiFetch).mockReset();
  vi.mocked(apiFetch).mockImplementation(async (path: string) => {
    throw new Error(`unexpected ${path}`);
  });
});
afterEach(() => {
  restore();
  vi.unstubAllGlobals();
});

describe("ServerLogsTab", () => {
  it("is also the default export, for next/dynamic", () => {
    expect(ServerLogsTabDefault).toBe(ServerLogsTab);
  });

  it("follows only the address's sources of this server", async () => {
    query(new URLSearchParams([["tab", "logs"], ["src", encodeSource(ELSEWHERE)], ["src", encodeSource(HERE)]]).toString());
    await tab();
    const ws = FakeWebSocket.instances[0];
    act(() => ws.open());
    expect(ws.sent).toEqual([{ type: "subscribe", sources: [wire(HERE)] }]);
    expect(screen.getByRole("link", { name: "Open in Logs" })).toHaveAttribute(
      "href",
      `/logs?${queryOf({ sources: [HERE], settings: DEFAULT_SETTINGS })}`,
    );
  });

  it("writes each change into the server's address, on the Logs tab", async () => {
    query(new URLSearchParams({ tab: "logs", src: encodeSource(HERE) }).toString());
    await tab();
    await userEvent.click(screen.getByRole("button", { name: "Wrap" }));
    expect(replace).toHaveBeenLastCalledWith(
      `/servers/${A}?tab=logs&${queryOf({ sources: [HERE], settings: { ...DEFAULT_SETTINGS, wrap: true } })}`,
    );
  });

  it("keeps only ?tab=logs when the change leaves every default", async () => {
    query("tab=logs&wrap=1");
    await tab();
    await userEvent.click(screen.getByRole("button", { name: "Wrap" }));
    expect(replace).toHaveBeenLastCalledWith(`/servers/${A}?tab=logs`);
  });

  it("links to the Logs page with nothing to carry when it shows the defaults", async () => {
    await tab();
    expect(screen.getByRole("link", { name: "Open in Logs" })).toHaveAttribute("href", "/logs");
  });

  it("adds sources for this server only, and has no Views menu", async () => {
    await tab();
    expect(screen.queryByRole("button", { name: "Views" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Add source" }));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).queryByRole("combobox", { name: "Server" })).not.toBeInTheDocument();
    expect(within(dialog).getByText("web-01")).toBeInTheDocument();
  });
});
