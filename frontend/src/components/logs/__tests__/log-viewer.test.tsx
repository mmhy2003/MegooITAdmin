import { act, fireEvent, render, screen, within } from "@testing-library/react";
import type { ComponentProps } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mockElementSize } from "@/__tests__/helpers/element-size";
import { FakeWebSocket, installFakeWebSocket } from "@/__tests__/helpers/fake-websocket";
import { server } from "@/components/dashboard/__tests__/fixtures";
import { LogViewer } from "@/components/logs/log-viewer";
import { apiFetch } from "@/lib/api";
import type { Container } from "@/lib/checks";
import { clock } from "@/lib/logs/download";
import { DEFAULT_SETTINGS, wire, type LogSource, type ViewSettings, type ViewState } from "@/lib/logs/sources";
import type { WireLine } from "@/lib/logs/socket";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), apiFetch: vi.fn() }));
vi.mock("@/lib/auth/navigate");

const A = "6f1c2a8e-4b3d-4e5f-9a0b-1c2d3e4f5a6b";
const GONE = "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d";
const WEB_01 = server("web-01", null, { id: A, can_view_logs: true });
const CONTAINER: LogSource = { kind: "container", server_id: A, container_id: "3f2a9b8c7d6e", name: "web" };
const JOURNAL: LogSource = { kind: "journal", server_id: A, unit: "nginx.service", priority: null, this_boot: false };
const T0 = Date.parse("2026-11-28T09:05:01.000Z");

function listed(container_id: string, name: string): Container {
  return {
    container_id, runtime: "docker", name, image: "nginx:1.27", compose_project: null, compose_service: null,
    state: "running", status: "Up 2 hours", first_seen_at: "2026-11-28T08:00:00Z", last_seen_at: "2026-11-28T09:00:00Z",
  };
}

let containers: Container[] = [listed("3f2a9b8c7d6e", "web")];

function stateOf(sources: LogSource[], settings: Partial<ViewSettings> = {}): ViewState {
  return { sources, settings: { ...DEFAULT_SETTINGS, ...settings } };
}

function lines(...texts: [number, string][]): WireLine[] {
  return texts.map(([seq, text]) => ({ seq, time: new Date(T0 + seq * 1000).toISOString(), text }));
}

type Props = ComponentProps<typeof LogViewer>;

async function flush() {
  await act(async () => {});
}

/** Renders the viewer and lets the containers arrive. */
async function view(state: ViewState, props: Partial<Props> = {}) {
  const onChange = vi.fn();
  const result = render(<LogViewer state={state} onChange={onChange} servers={[WEB_01]} {...props} />);
  await flush();
  return { ...result, onChange };
}

function socket(): FakeWebSocket {
  expect(FakeWebSocket.instances).toHaveLength(1);
  return FakeWebSocket.instances[0];
}

/** Opens the socket, answers the subscription with ids s0, s1… and sends each source's backlog. */
function follow(sources: LogSource[], backlogs: WireLine[][]) {
  const ws = socket();
  act(() => ws.open());
  const subscribed = sources.map((s, i) => ({ id: `s${i}`, source: wire(s) }));
  act(() => ws.receive({ type: "subscribed", sources: subscribed, denied: [] }));
  backlogs.forEach((backlog, i) => {
    act(() => ws.receive({ type: "lines", source: `s${i}`, lines: backlog, backlog: true }));
  });
  return ws;
}

const subscribes = (ws: FakeWebSocket) => ws.sent.filter((m) => (m as { type: string }).type === "subscribe");

let restore: () => void;
beforeEach(() => {
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval"] });
  vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => {
    cb(0);
    return 0;
  });
  vi.stubGlobal("cancelAnimationFrame", () => {});
  installFakeWebSocket();
  restore = mockElementSize();
  containers = [listed("3f2a9b8c7d6e", "web")];
  vi.mocked(apiFetch).mockImplementation(async (path: string) => {
    if (path === `/servers/${A}/containers`) return containers;
    throw new Error(`unexpected ${path}`);
  });
});
afterEach(() => {
  restore();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("LogViewer", () => {
  it("opens one socket and subscribes to the sources in their wire form", async () => {
    await view(stateOf([CONTAINER, JOURNAL]));
    const ws = socket();
    expect(ws.sent).toEqual([]);
    act(() => ws.open());
    expect(ws.sent).toEqual([{ type: "subscribe", sources: [wire(CONTAINER), wire(JOURNAL)] }]);
    expect(apiFetch).toHaveBeenCalledWith(`/servers/${A}/containers`);
  });

  it("shows each source in its own pane, side by side, with its lines", async () => {
    await view(stateOf([CONTAINER, JOURNAL]));
    follow([CONTAINER, JOURNAL], [lines([1, "GET /index.html 200"]), lines([1, "nginx started"], [2, "worker up"])]);
    const web = screen.getByRole("log", { name: "web-01 · Container · web" });
    const journal = screen.getByRole("log", { name: "web-01 · Journal · nginx.service" });
    expect(within(web).getByText("GET /index.html 200")).toBeInTheDocument();
    expect(within(journal).getByText("nginx started")).toBeInTheDocument();
    expect(within(journal).getByText("worker up")).toBeInTheDocument();
    expect(web.closest(".grid")).toHaveClass("gap-4", "md:grid-cols-2", "xl:grid-cols-3");
    expect(screen.getAllByText("Live", { selector: "[data-slot=badge]" })).toHaveLength(2);
  });

  it("hides the lines the filter or the levels leave out, and marks the matches", async () => {
    const { rerender, onChange } = await view(stateOf([JOURNAL], { q: "worker" }));
    follow([JOURNAL], [lines([1, "nginx started"], [2, "ERROR worker down"], [3, "INFO worker up"])]);
    expect(screen.queryByText("nginx started")).not.toBeInTheDocument();
    expect(screen.getAllByText("worker", { selector: "mark.log-match" })).toHaveLength(2);
    expect(screen.getByText("2 of 3 lines match")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Info" }));
    const next = onChange.mock.calls[0][0] as ViewState;
    expect(next.settings.levels).toEqual(["error", "warning", "debug", "none"]);
    rerender(<LogViewer state={next} onChange={onChange} servers={[WEB_01]} />);
    expect(screen.queryByText(/worker up/)).not.toBeInTheDocument();
    expect(screen.getByText("1 of 3 lines match")).toBeInTheDocument();
  });

  it("merges the sources into one pane in time order, tagged by source", async () => {
    await view(stateOf([CONTAINER, JOURNAL], { layout: "merged" }));
    follow([CONTAINER, JOURNAL], [lines([1, "container one"], [3, "container three"]), lines([2, "journal two"])]);
    const pane = screen.getByRole("log", { name: "Merged · 2 sources" });
    const texts = within(pane).getAllByText(/^(container|journal) /).map((el) => el.textContent);
    expect(texts).toEqual(["container one", "journal two", "container three"]);
    expect(within(pane).getAllByText("web-01 · Container · web", { selector: ".log-tag-0" })).toHaveLength(2);
    const journal = within(pane).getByText("web-01 · Journal · nginx.service", { selector: ".log-tag-1" });
    expect(journal).toBeInTheDocument();
    expect(screen.getAllByRole("log")).toHaveLength(1);
  });

  it("shows the times in the viewer's zone or in UTC", async () => {
    // Three hours east of UTC, whatever zone the tests run in.
    vi.spyOn(Date.prototype, "getHours").mockImplementation(function (this: Date) {
      return (this.getUTCHours() + 3) % 24;
    });
    const { rerender, onChange } = await view(stateOf([JOURNAL]));
    follow([JOURNAL], [lines([1, "nginx started"])]);
    expect(screen.getByText("12:05:02.000")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "UTC" }));
    const next = onChange.mock.calls[0][0] as ViewState;
    expect(next.settings.utc).toBe(true);
    rerender(<LogViewer state={next} onChange={onChange} servers={[WEB_01]} />);
    expect(screen.getByText(clock(T0 + 1000, true))).toBeInTheDocument();
    expect(screen.getByText("09:05:02.000")).toBeInTheDocument();
  });

  it("follows a recreated container by its name, and says so before it subscribes", async () => {
    const { rerender, onChange } = await view(stateOf([JOURNAL]));
    const ws = socket();
    act(() => ws.open());
    // The containers arrive while the socket is open: onChange must come before the next subscribe.
    let answer: (list: Container[]) => void = () => {};
    vi.mocked(apiFetch).mockImplementation(() => new Promise((resolve) => (answer = resolve as typeof answer)));
    const sentAtChange: number[] = [];
    onChange.mockImplementation(() => sentAtChange.push(subscribes(ws).length));
    rerender(<LogViewer state={stateOf([CONTAINER, JOURNAL])} onChange={onChange} servers={[WEB_01]} />);
    await flush();
    expect(subscribes(ws)).toHaveLength(1);

    await act(async () => answer([listed("9e8d7c6b5a4f", "web"), listed("1a2b3c4d5e6f", "db")]));
    const swapped: LogSource = { ...CONTAINER, container_id: "9e8d7c6b5a4f" };
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith(stateOf([swapped, JOURNAL]));
    expect(sentAtChange).toEqual([1]);
    expect(subscribes(ws)).toEqual([
      { type: "subscribe", sources: [wire(JOURNAL)] },
      { type: "subscribe", sources: [wire(swapped), wire(JOURNAL)] },
    ]);
  });

  it("reads the containers again for an ID the last list lacks, never swapping back to an old one", async () => {
    const { rerender, onChange } = await view(stateOf([CONTAINER]));
    expect(apiFetch).toHaveBeenCalledTimes(1);
    // Compose recreated web: the person adds the new one, which the list read at mount does not hold.
    containers = [listed("9e8d7c6b5a4f", "web")];
    const fresh: LogSource = { ...CONTAINER, container_id: "9e8d7c6b5a4f" };
    rerender(<LogViewer state={stateOf([fresh])} onChange={onChange} servers={[WEB_01]} />);
    await flush();
    expect(apiFetch).toHaveBeenCalledTimes(2);
    expect(onChange).not.toHaveBeenCalled();
    const ws = socket();
    act(() => ws.open());
    expect(subscribes(ws).at(-1)).toEqual({ type: "subscribe", sources: [wire(fresh)] });
  });

  it("reads the containers again after a failed read", async () => {
    vi.mocked(apiFetch).mockRejectedValueOnce(new Error("unreachable"));
    const { rerender, onChange } = await view(stateOf([CONTAINER]));
    rerender(<LogViewer state={stateOf([CONTAINER, JOURNAL])} onChange={onChange} servers={[WEB_01]} />);
    await flush();
    expect(apiFetch).toHaveBeenCalledTimes(2);
  });

  it("does not read the containers again while its sources stay the same", async () => {
    const { rerender, onChange } = await view(stateOf([CONTAINER]));
    rerender(<LogViewer state={stateOf([CONTAINER], { q: "web" })} onChange={onChange} servers={[WEB_01]} />);
    await flush();
    expect(apiFetch).toHaveBeenCalledTimes(1);
  });

  it("pauses after 30 minutes without activity, and Resume subscribes again", async () => {
    await view(stateOf([CONTAINER, JOURNAL]));
    const ws = follow([CONTAINER, JOURNAL], [lines([1, "a"]), lines([1, "b"])]);
    expect(screen.queryByText("Paused after 30 minutes without activity.")).not.toBeInTheDocument();
    act(() => ws.receive({ type: "ended", source: "s0", reason: "idle" }));
    expect(screen.queryByText("Paused after 30 minutes without activity.")).not.toBeInTheDocument();
    act(() => ws.receive({ type: "ended", source: "s1", reason: "idle" }));
    expect(screen.getByText("Paused after 30 minutes without activity.")).toBeInTheDocument();
    expect(subscribes(ws).at(-1)).toEqual({ type: "subscribe", sources: [] });

    fireEvent.click(screen.getByRole("button", { name: "Resume" }));
    expect(subscribes(ws).at(-1)).toEqual({ type: "subscribe", sources: [wire(CONTAINER), wire(JOURNAL)] });
    expect(screen.queryByText("Paused after 30 minutes without activity.")).not.toBeInTheDocument();
  });

  it("tells the worker someone is watching on a key press inside, once", async () => {
    await view(stateOf([JOURNAL]));
    const ws = follow([JOURNAL], [lines([1, "a"])]);
    const pane = screen.getByRole("log", { name: "web-01 · Journal · nginx.service" });
    fireEvent.keyDown(pane, { key: "ArrowUp" });
    fireEvent.keyDown(pane, { key: "ArrowUp" });
    expect(ws.sent.filter((m) => (m as { type: string }).type === "active")).toEqual([{ type: "active" }]);
  });

  it("removes a pane's source through onChange", async () => {
    const { onChange } = await view(stateOf([CONTAINER, JOURNAL]));
    fireEvent.click(screen.getByRole("button", { name: "Remove Container · web" }));
    expect(onChange).toHaveBeenCalledWith(stateOf([JOURNAL]));
  });

  it("closes its socket when it goes", async () => {
    const { unmount } = await view(stateOf([JOURNAL]));
    const ws = socket();
    act(() => ws.open());
    unmount();
    expect(ws.closedByClient).toBe(true);
  });

  it("adds the sources of its dialog through onChange", async () => {
    const { onChange } = await view(stateOf([CONTAINER]), { serverId: A });
    fireEvent.click(screen.getByRole("button", { name: "Add source" }));
    const dialog = within(screen.getByRole("dialog", { name: "Add source" }));
    fireEvent.click(dialog.getByRole("button", { name: "Add" }));
    expect(onChange).toHaveBeenCalledWith(stateOf([CONTAINER, { ...JOURNAL, unit: null }]));
  });

  it.each([true, false])("offers Manage patterns on a refused file when the allowlist says can_manage %s",
    async (canManage) => {
      const file: LogSource = { kind: "file", server_id: A, path: "/etc/shadow" };
      vi.mocked(apiFetch).mockImplementation(async (path: string) => {
        if (path === "/server-groups/g/log-allowlist") return { can_manage: canManage, patterns: [] };
        throw new Error(`unexpected ${path}`);
      });
      await view(stateOf([file, JOURNAL]));
      const ws = socket();
      act(() => ws.open());
      act(() => ws.receive({
        type: "subscribed", sources: [{ id: "s1", source: wire(JOURNAL) }],
        denied: [{ source: wire(file), reason: "not_allowed" }],
      }));
      await flush();
      const reads = vi.mocked(apiFetch).mock.calls.filter(([p]) => p === "/server-groups/g/log-allowlist");
      expect(reads).toHaveLength(1);
      expect(screen.getByText("This file matches none of the group's log file patterns.")).toBeInTheDocument();
      const manage = screen.queryByRole("button", { name: "Manage patterns" });
      if (!canManage) {
        expect(manage).not.toBeInTheDocument();
        return;
      }
      fireEvent.click(manage!);
      await flush();
      expect(screen.getByRole("heading", { name: "Log file patterns of Production" })).toBeInTheDocument();
    });

  it("titles a source of a server it does not know Unknown server", async () => {
    const lost: LogSource = { ...JOURNAL, server_id: GONE };
    await view(stateOf([lost]));
    expect(screen.getByRole("log", { name: "Unknown server · Journal · nginx.service" })).toBeInTheDocument();
    expect(screen.getByText("Unknown server")).toBeInTheDocument();
  });
});
