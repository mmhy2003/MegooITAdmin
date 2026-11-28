import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mockElementSize } from "@/__tests__/helpers/element-size";
import { LogPane, REASONS } from "@/components/logs/log-pane";
import { downloadName, downloadText } from "@/lib/logs/download";
import type { LogSource } from "@/lib/logs/sources";
import { sourceLabel } from "@/lib/logs/sources";
import type { LineRow, PaneState, Row, SourceEntry } from "@/lib/logs/store";

const SERVER = "6f1c2a8e-4b3d-4e5f-9a0b-1c2d3e4f5a6b";
const T0 = Date.parse("2026-11-28T09:05:01.123Z");
const JOURNAL: LogSource = { kind: "journal", server_id: SERVER, unit: "nginx.service", priority: null, this_boot: false };
const CONTAINER: LogSource = { kind: "container", server_id: SERVER, container_id: "3f2a9b8c7d6e5f4a", name: "web" };

function line(source: string, seq: number, text = `line ${seq}`): LineRow {
  return {
    kind: "line", key: `${source}:0:${seq}`, source, run: 0, seq, time: new Date(T0 + seq).toISOString(),
    ms: T0 + seq, text, plain: text, level: "none", unit: null, truncated: false,
  };
}

function entry(state: PaneState, extra: Partial<SourceEntry> = {}): SourceEntry {
  return {
    id: "a", source: JOURNAL, rows: [], trimmed: 0, state, skipped: 0, retries: 0, wireId: null, run: 0, ...extra,
  };
}

type Props = ComponentProps<typeof LogPane>;

function pane(props: Partial<Props> = {}) {
  const one = props.entry === undefined ? entry({ state: "live" }) : props.entry;
  const all: Props = {
    title: "web-01", entry: one, entries: one ? [one] : [], rows: [], socket: "live", utc: true, wrap: false,
    filter: null, merged: null, onRemove: vi.fn(), onRetryNow: vi.fn(), onReconnect: vi.fn(),
    downloadParts: ["web-01", "nginx.service"], ...props,
  };
  return <LogPane {...all} />;
}

let restore: () => void;
beforeEach(() => {
  restore = mockElementSize();
});
afterEach(() => {
  restore();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("LogPane", () => {
  it("shows the server, the source and the skipped total in its header", () => {
    render(pane({ entry: entry({ state: "live" }, { skipped: 1240 }) }));
    expect(screen.getByText("web-01")).toBeInTheDocument();
    expect(screen.getByText(sourceLabel(JOURNAL))).toBeInTheDocument();
    expect(screen.getByText("1,240 skipped")).toBeInTheDocument();
  });

  it.each<[PaneState, string]>([
    [{ state: "opening" }, "Connecting"],
    [{ state: "live" }, "Live"],
    [{ state: "retrying", reason: "unreachable", attempt: 1, at: Date.now() + 2000 }, "Retrying"],
    [{ state: "ended", reason: "exited", status: 1 }, "Ended"],
    [{ state: "denied", reason: "forbidden" }, "Refused"],
    [{ state: "idle" }, "Paused"],
  ])("badges %o as %s", (state, badge) => {
    render(pane({ entry: entry(state) }));
    expect(screen.getByText(badge, { selector: "[data-slot=badge]" })).toBeInTheDocument();
  });

  it("badges Reconnecting while the socket reconnects", () => {
    render(pane({ socket: "reconnecting" }));
    expect(screen.getByText("Reconnecting", { selector: "[data-slot=badge]" })).toBeInTheDocument();
  });

  it("badges Paused while the list is scrolled up", () => {
    const rows = Array.from({ length: 50 }, (_, i) => line("a", i + 1));
    render(pane({ rows }));
    const scroller = screen.getByRole("log");
    act(() => {
      scroller.scrollTop = 100;
      fireEvent.scroll(scroller);
    });
    expect(screen.getByText("Paused", { selector: "[data-slot=badge]" })).toBeInTheDocument();
  });

  it.each(Object.entries(REASONS).filter(([reason]) => reason !== "exited"))("says why for %s", (reason, text) => {
    render(pane({ entry: entry({ state: "denied", reason }) }));
    expect(screen.getByText(text)).toBeInTheDocument();
  });

  it("puts the status in the exited text, and falls back for an unknown reason", () => {
    const { rerender } = render(pane({ entry: entry({ state: "ended", reason: "exited", status: 137 }) }));
    expect(screen.getByText("The command ended with status 137.")).toBeInTheDocument();
    rerender(pane({ entry: entry({ state: "ended", reason: "gremlins", status: null }) }));
    expect(screen.getByText("The stream ended (gremlins).")).toBeInTheDocument();
  });

  it("counts down to the next try each second, and Try now tries at once", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "Date"] });
    const onRetryNow = vi.fn();
    const state: PaneState = { state: "retrying", reason: "unreachable", attempt: 2, at: Date.now() + 5000 };
    render(pane({ entry: entry(state), onRetryNow }));
    expect(screen.getByText("The server is not answering. Trying again in 5 s (2 of 5).")).toBeInTheDocument();
    act(() => vi.advanceTimersByTime(1000));
    expect(screen.getByText("The server is not answering. Trying again in 4 s (2 of 5).")).toBeInTheDocument();
    vi.useRealTimers();
    await userEvent.click(screen.getByRole("button", { name: "Try now" }));
    expect(onRetryNow).toHaveBeenCalledWith("a");
  });

  it("keeps its lines when ended, and Reconnect reconnects", async () => {
    const onReconnect = vi.fn();
    const rows = [line("a", 1, "last words")];
    render(pane({ entry: entry({ state: "ended", reason: "not_readable", status: null }), rows, onReconnect }));
    expect(screen.getByText("last words")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Reconnect" }));
    expect(onReconnect).toHaveBeenCalledWith("a");
  });

  it("offers Manage patterns only for not_allowed, to those who may", async () => {
    const onManagePatterns = vi.fn();
    const { rerender } = render(pane({ entry: entry({ state: "denied", reason: "not_allowed" }), onManagePatterns }));
    await userEvent.click(screen.getByRole("button", { name: "Manage patterns" }));
    expect(onManagePatterns).toHaveBeenCalledWith("a");
    rerender(pane({ entry: entry({ state: "denied", reason: "not_allowed" }) }));
    expect(screen.queryByRole("button", { name: "Manage patterns" })).not.toBeInTheDocument();
    rerender(pane({ entry: entry({ state: "denied", reason: "forbidden" }), onManagePatterns }));
    expect(screen.queryByRole("button", { name: "Manage patterns" })).not.toBeInTheDocument();
  });

  it("removes itself", async () => {
    const onRemove = vi.fn();
    render(pane({ onRemove }));
    await userEvent.click(screen.getByRole("button", { name: `Remove ${sourceLabel(JOURNAL)}` }));
    expect(onRemove).toHaveBeenCalledWith("a");
  });

  function stubDownload() {
    const blobs: Blob[] = [];
    vi.stubGlobal("URL", Object.assign(URL, {
      createObjectURL: vi.fn((blob: Blob) => {
        blobs.push(blob);
        return "blob:pane";
      }),
      revokeObjectURL: vi.fn(),
    }));
    const names: string[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      names.push(this.download);
    });
    return { blobs, names };
  }

  it("downloads the lines it holds", async () => {
    const { blobs, names } = stubDownload();
    const rows: Row[] = [line("a", 1), line("a", 2)];
    render(pane({ rows }));
    const before = new Date();
    await userEvent.click(screen.getByRole("button", { name: `Download ${sourceLabel(JOURNAL)}` }));
    expect(await blobs[0].text()).toBe(downloadText(rows, { utc: true, labels: null }));
    expect([downloadName(["web-01", "nginx.service"], before), downloadName(["web-01", "nginx.service"], new Date())])
      .toContain(names[0]);
  });

  it("titles a merged pane by its count, and its download carries the labels", async () => {
    const { blobs } = stubDownload();
    const a = entry({ state: "live" }, { id: "a", skipped: 10 });
    const b = entry({ state: "live" }, { id: "b", source: CONTAINER, skipped: 5 });
    const rows: Row[] = [line("a", 1), line("b", 1)];
    const labels = new Map([["a", "web-01 · nginx.service"], ["b", "web-01 · web"]]);
    const tags = new Map([["a", { text: "web-01 · nginx.service", tone: 0 }], ["b", { text: "web-01 · web", tone: 1 }]]);
    render(pane({ entry: null, entries: [a, b], rows, merged: { labels, tags }, downloadParts: ["merged"] }));
    expect(screen.getByText("Merged · 2 sources")).toBeInTheDocument();
    expect(screen.getByText("15 skipped")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Download Merged · 2 sources" }));
    expect(await blobs[0].text()).toBe(downloadText(rows, { utc: true, labels }));
  });

  it("says each merged source's state with its label", async () => {
    const onReconnect = vi.fn();
    const a = entry({ state: "live" }, { id: "a" });
    const b = entry({ state: "ended", reason: "not_available", status: null }, { id: "b", source: CONTAINER });
    const labels = new Map([["a", "web-01 · nginx.service"], ["b", "web-01 · web"]]);
    render(pane({ entry: null, entries: [a, b], merged: { labels, tags: new Map() }, onReconnect }));
    expect(screen.getByText("web-01 · web: This source is not available on this server.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Reconnect" }));
    expect(onReconnect).toHaveBeenCalledWith("b");
  });
});
