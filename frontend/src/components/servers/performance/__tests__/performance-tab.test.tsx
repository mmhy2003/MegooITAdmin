import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { PerformanceCardProps } from "@/components/servers/performance/metric-card";
import { PerformanceTab } from "@/components/servers/performance/performance-tab";
import { type LiveMetricsOptions, useLiveMetrics } from "@/hooks/use-live-metrics";
import type { RangeName, SampleMessage } from "@/lib/metrics";
import type { Server } from "@/lib/servers";

vi.mock("@/hooks/use-live-metrics", () => ({ useLiveMetrics: vi.fn() }));

function fake(name: string) {
  return function Card(p: PerformanceCardProps) {
    return (
      <div data-testid={name}>
        {`${p.serverId}|${p.range}|${p.sample ? p.sample.time : "none"}|${p.refill}|${p.interval}`}
      </div>
    );
  };
}

vi.mock("@/components/servers/performance/cpu-card", () => ({ CpuCard: fake("cpu") }));
vi.mock("@/components/servers/performance/memory-card", () => ({ MemoryCard: fake("memory") }));
vi.mock("@/components/servers/performance/load-card", () => ({ LoadCard: fake("load") }));
vi.mock("@/components/servers/performance/network-card", () => ({ NetworkCard: fake("network") }));
vi.mock("@/components/servers/performance/disk-io-card", () => ({ DiskIoCard: fake("disk-io") }));
vi.mock("@/components/servers/performance/filesystems-card", () => ({ FilesystemsCard: fake("filesystems") }));

const CARDS = ["cpu", "memory", "load", "network", "disk-io", "filesystems"];

const SERVER = { id: "s-1", name: "db-01", os: "linux", metrics_interval_seconds: 5 } as Server;

const SAMPLE: SampleMessage = {
  type: "sample",
  server_id: "s-1",
  time: "2026-11-26T10:00:05Z",
  readings: [["cpu.used_percent", "", 42]],
};

function options(): LiveMetricsOptions {
  return vi.mocked(useLiveMetrics).mock.lastCall![0];
}

function show(range: RangeName, onRange = vi.fn()) {
  return render(<PerformanceTab server={SERVER} range={range} onRange={onRange} />);
}

beforeEach(() => {
  vi.mocked(useLiveMetrics).mockReset();
  vi.mocked(useLiveMetrics).mockReturnValue("live");
});

describe("PerformanceTab", () => {
  it("opens one socket for the full readings of this server", () => {
    show("live");
    expect(options().view).toBe("full");
    expect(options().serverIds).toEqual(["s-1"]);
    expect(options().enabled ?? true).toBe(true);
  });

  it("passes the socket's newest sample to every card on Live", () => {
    show("live");
    for (const name of CARDS) expect(screen.getByTestId(name)).toHaveTextContent("s-1|live|none|0|5");

    act(() => options().onMessage(SAMPLE));
    for (const name of CARDS) expect(screen.getByTestId(name)).toHaveTextContent(`s-1|live|${SAMPLE.time}|0|5`);
    expect(screen.getByRole("status")).toHaveTextContent("Live");
  });

  it("passes no sample on a past range but keeps the socket open, without the live badge", () => {
    show("7d");
    act(() => options().onMessage(SAMPLE));
    for (const name of CARDS) expect(screen.getByTestId(name)).toHaveTextContent("s-1|7d|none|0|5");
    expect(options().enabled ?? true).toBe(true);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("ignores messages that are not samples", () => {
    show("live");
    act(() => options().onMessage({ type: "subscribed", server_ids: ["s-1"], denied: [] }));
    expect(screen.getByTestId("cpu")).toHaveTextContent("s-1|live|none|0|5");
  });

  it("refills every card each time the socket opens", () => {
    show("24h");
    act(() => options().onOpen());
    for (const name of CARDS) expect(screen.getByTestId(name)).toHaveTextContent("s-1|24h|none|1|5");
    act(() => options().onOpen());
    expect(screen.getByTestId("cpu")).toHaveTextContent("s-1|24h|none|2|5");
  });

  it("offers every range, marks the chosen one and reports a click", async () => {
    const onRange = vi.fn();
    show("live", onRange);
    const group = screen.getByRole("group", { name: "Time range" });
    expect(group.querySelectorAll("button")).toHaveLength(7);
    expect(screen.getByRole("button", { name: "Live" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "7 days" })).toHaveAttribute("aria-pressed", "false");

    await userEvent.setup().click(screen.getByRole("button", { name: "7 days" }));
    expect(onRange).toHaveBeenCalledWith("7d");
  });
});
