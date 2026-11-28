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
import { encodeSource, wire, type LogSource } from "@/lib/logs/sources";
import type { Server } from "@/lib/servers";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), apiFetch: vi.fn() }));
vi.mock("@/lib/auth/navigate");

const A = "6f1c2a8e-4b3d-4e5f-9a0b-1c2d3e4f5a6b";
const WEB_01 = server("web-01", null, { id: A, can_view_logs: true });
const JOURNAL: LogSource = { kind: "journal", server_id: A, unit: "nginx.service", priority: null, this_boot: false };

let replace: ReturnType<typeof vi.fn>;
let servers: Server[] | Error = [WEB_01];

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
  query("");
  vi.mocked(apiFetch).mockImplementation(async (path: string) => {
    if (path === "/servers") {
      if (servers instanceof Error) throw servers;
      return servers;
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
});
