import { act, render, renderHook, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CpuCard } from "@/components/servers/performance/cpu-card";
import { LoadCard } from "@/components/servers/performance/load-card";
import { MemoryCard } from "@/components/servers/performance/memory-card";
import { useSeries } from "@/components/servers/performance/use-series";
import { useRefresh } from "@/hooks/use-refresh";
import { ApiError, apiFetch } from "@/lib/api";
import type { ChartLine, RangeName, SampleMessage, Series, SeriesAnswer } from "@/lib/metrics";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), apiFetch: vi.fn() }));
vi.mock("@/lib/auth/navigate");
vi.mock("@/hooks/use-refresh", () => ({ useRefresh: vi.fn() }));
vi.mock("@/components/servers/performance/metric-chart", () => ({
  MetricChart: (p: { lines: ChartLine[]; dimmed?: boolean }) => (
    <div data-testid="chart" data-dimmed={String(!!p.dimmed)}>
      {p.lines.map((l) => `${l.label}:${l.series.time.length}`).join(",")}
    </div>
  ),
}));

const T0 = "2026-11-26T10:00:00Z";
const T1 = "2026-11-26T10:00:05Z";
const GIB = 1024 ** 3;

function series(metric: string, values: number[], instance = ""): Series {
  return {
    metric,
    instance,
    time: values.map((_, i) => new Date(Date.parse(T0) + i * 5_000).toISOString()),
    avg: values,
    min: values.map(() => null),
    max: values.map(() => null),
  };
}

function answer(range: RangeName, list: Series[]): SeriesAnswer {
  return { range, step_seconds: range === "live" ? null : 60, start: T0, end: T1, series: list };
}

const CPU = [
  series("cpu.used_percent", [40, 42]),
  series("cpu.used_percent", [10, 20], "cpu1"),
  series("cpu.used_percent", [30, 35], "cpu0"),
  series("cpu.user_percent", [30, 31.6]),
  series("cpu.system_percent", [8, 9]),
  series("cpu.iowait_percent", [1, 2]),
  series("cpu.steal_percent", [0, 0]),
];
const MEMORY = [
  series("mem.used_bytes", [4 * GIB, 5 * GIB, 6 * GIB]),
  series("swap.used_bytes", [0, GIB, GIB]),
  series("mem.total_bytes", [16 * GIB, 16 * GIB, 16 * GIB]),
  series("swap.total_bytes", [2 * GIB, 2 * GIB, 2 * GIB]),
];
const LOAD = [series("load.1m", [1, 2]), series("load.5m", [1, 1]), series("load.15m", [0.5, 0.5])];

const PROPS = { serverId: "s1", range: "live" as RangeName, sample: null, refill: 0, interval: 5 };

/** Answers each metrics read with `list` for its range. */
function mockReads(list: Series[]) {
  vi.mocked(apiFetch).mockImplementation(async (path: string) => {
    const range = new URLSearchParams(path.split("?")[1]).get("range") as RangeName;
    return answer(range, list);
  });
}

beforeEach(() => {
  vi.mocked(apiFetch).mockReset();
  vi.mocked(useRefresh).mockReset();
});

describe("useSeries", () => {
  it("reads the metrics of the range in the foreground", async () => {
    mockReads(LOAD);
    const { result } = renderHook(() => useSeries("s1", ["load.1m", "load.5m"], "6h", null, 0));
    await waitFor(() => expect(result.current.answer).not.toBeNull());
    expect(apiFetch).toHaveBeenCalledWith("/servers/s1/metrics?range=6h&metric=load.1m&metric=load.5m", {
      background: false,
    });
    expect(result.current.loading).toBe(false);
  });

  it("re-reads when refill changes", async () => {
    mockReads(LOAD);
    const { result, rerender } = renderHook(({ refill }) => useSeries("s1", ["load.1m"], "live", null, refill), {
      initialProps: { refill: 0 },
    });
    await waitFor(() => expect(result.current.answer).not.toBeNull());
    rerender({ refill: 1 });
    await waitFor(() => expect(apiFetch).toHaveBeenCalledTimes(2));
  });

  it("re-reads in the background on the history refresh, and keeps everything when that fails", async () => {
    mockReads(LOAD);
    const { result } = renderHook(() => useSeries("s1", ["load.1m"], "24h", null, 0));
    await waitFor(() => expect(result.current.answer).not.toBeNull());
    const [refresh, active, everyMs] = vi.mocked(useRefresh).mock.lastCall!;
    expect(active).toBe(true);
    expect(everyMs).toBe(60_000);

    vi.mocked(apiFetch).mockRejectedValueOnce(new ApiError(0, "unreachable"));
    await act(async () => refresh());
    expect(apiFetch).toHaveBeenLastCalledWith("/servers/s1/metrics?range=24h&metric=load.1m", { background: true });
    expect(result.current.failed).toBe(false);
    expect(result.current.answer?.series).toHaveLength(3);
  });

  it("does not refresh in the background while live", () => {
    mockReads(LOAD);
    renderHook(() => useSeries("s1", ["load.1m"], "live", null, 0));
    expect(vi.mocked(useRefresh).mock.lastCall![1]).toBe(false);
  });

  it("ignores an older read that answers after a newer one", async () => {
    let first: (a: SeriesAnswer) => void = () => {};
    vi.mocked(apiFetch)
      .mockImplementationOnce(() => new Promise((resolve) => (first = resolve as typeof first)))
      .mockResolvedValueOnce(answer("6h", LOAD));
    const { result, rerender } = renderHook(({ range }) => useSeries("s1", ["load.1m"], range, null, 0), {
      initialProps: { range: "1h" as RangeName },
    });
    rerender({ range: "6h" });
    await waitFor(() => expect(result.current.answer?.range).toBe("6h"));
    await act(async () => first(answer("1h", [])));
    expect(result.current.answer?.range).toBe("6h");
  });

  it("appends a live sample of its server only", async () => {
    mockReads(LOAD);
    const sample = (server_id: string): SampleMessage => ({
      type: "sample",
      server_id,
      time: "2026-11-26T10:00:10Z",
      readings: [["load.1m", "", 3]],
    });
    const { result, rerender } = renderHook(
      ({ s }: { s: SampleMessage | null }) => useSeries("s1", ["load.1m"], "live", s, 0),
      { initialProps: { s: null as SampleMessage | null } },
    );
    await waitFor(() => expect(result.current.answer).not.toBeNull());
    rerender({ s: sample("s2") });
    expect(result.current.answer?.series[0].avg).toEqual([1, 2]);
    rerender({ s: sample("s1") });
    expect(result.current.answer?.series[0].avg).toEqual([1, 2, 3]);
  });
});

describe("CpuCard", () => {
  it("draws CPU used with the user, system, I/O wait and steal numbers and a chart per core", async () => {
    mockReads(CPU);
    render(<CpuCard {...PROPS} />);
    expect(await screen.findByTestId("chart")).toHaveTextContent("CPU used:2");
    expect(screen.getByRole("heading", { name: "CPU" })).toBeInTheDocument();
    expect(screen.getByText("User").nextElementSibling).toHaveTextContent("32%");
    expect(screen.getByText("System").nextElementSibling).toHaveTextContent("9%");
    expect(screen.getByText("I/O wait").nextElementSibling).toHaveTextContent("2%");
    expect(screen.getByText("Steal").nextElementSibling).toHaveTextContent("0%");
    expect(screen.getAllByRole("img").map((img) => img.getAttribute("aria-label"))).toEqual([
      "cpu0, CPU used",
      "cpu1, CPU used",
    ]);
  });

  it("asks for the five CPU metrics", async () => {
    mockReads(CPU);
    render(<CpuCard {...PROPS} />);
    await screen.findByTestId("chart");
    expect(apiFetch).toHaveBeenCalledWith(
      "/servers/s1/metrics?range=live&metric=cpu.used_percent&metric=cpu.user_percent&metric=cpu.system_percent" +
        "&metric=cpu.iowait_percent&metric=cpu.steal_percent",
      { background: false },
    );
  });

  it("grows the chart by one point for a live sample", async () => {
    mockReads(CPU);
    const { rerender } = render(<CpuCard {...PROPS} />);
    expect(await screen.findByTestId("chart")).toHaveTextContent("CPU used:2");
    const sample: SampleMessage = {
      type: "sample",
      server_id: "s1",
      time: "2026-11-26T10:00:10Z",
      readings: [["cpu.used_percent", "", 50]],
    };
    rerender(<CpuCard {...PROPS} sample={sample} />);
    expect(screen.getByTestId("chart")).toHaveTextContent("CPU used:3");
  });
});

describe("MemoryCard", () => {
  it("draws memory and swap used of the total", async () => {
    mockReads(MEMORY);
    render(<MemoryCard {...PROPS} />);
    expect(await screen.findByTestId("chart")).toHaveTextContent("Memory used:3,Swap used:3");
    expect(screen.getByText("of 16 GiB")).toBeInTheDocument();
  });
});

describe("LoadCard", () => {
  it("draws the 1, 5 and 15 minute load", async () => {
    mockReads(LOAD);
    render(<LoadCard {...PROPS} />);
    expect(await screen.findByTestId("chart")).toHaveTextContent("1 minute:2,5 minutes:2,15 minutes:2");
  });

  it("says there is no data in a range without points", async () => {
    mockReads([series("load.1m", []), series("load.5m", []), series("load.15m", [])]);
    render(<LoadCard {...PROPS} />);
    expect(await screen.findByText("No data in this range")).toBeInTheDocument();
    expect(screen.queryByTestId("chart")).not.toBeInTheDocument();
  });

  it("says there is no data when the answer has no series", async () => {
    mockReads([]);
    render(<LoadCard {...PROPS} />);
    expect(await screen.findByText("No data in this range")).toBeInTheDocument();
  });

  it("offers to try again after a failed read, and reads again", async () => {
    vi.mocked(apiFetch).mockRejectedValueOnce(new ApiError(500, "error"));
    render(<LoadCard {...PROPS} />);
    expect(await screen.findByText("Could not read this chart.")).toBeInTheDocument();
    mockReads(LOAD);
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByTestId("chart")).toHaveTextContent("1 minute:2");
    expect(apiFetch).toHaveBeenCalledTimes(2);
  });

  it("keeps the older chart and says it could not refresh when a new range fails", async () => {
    mockReads(LOAD);
    const { rerender } = render(<LoadCard {...PROPS} />);
    await screen.findByTestId("chart");
    vi.mocked(apiFetch).mockRejectedValueOnce(new ApiError(500, "error"));
    rerender(<LoadCard {...PROPS} range="6h" />);
    expect(await screen.findByText(/Could not refresh/)).toBeInTheDocument();
    expect(screen.getByTestId("chart")).toHaveTextContent("1 minute:2");
    expect(screen.getByTestId("chart")).toHaveAttribute("data-dimmed", "false");
  });

  it("keeps the previous chart dimmed while a new range loads", async () => {
    mockReads(LOAD);
    const { rerender } = render(<LoadCard {...PROPS} />);
    expect(await screen.findByTestId("chart")).toHaveAttribute("data-dimmed", "false");
    let resolve: (a: SeriesAnswer) => void = () => {};
    vi.mocked(apiFetch).mockImplementationOnce(() => new Promise((r) => (resolve = r as typeof resolve)));
    rerender(<LoadCard {...PROPS} range="7d" />);
    expect(screen.getByTestId("chart")).toHaveAttribute("data-dimmed", "true");
    await act(async () => resolve(answer("7d", [series("load.1m", [1, 2, 3, 4])])));
    expect(screen.getByTestId("chart")).toHaveAttribute("data-dimmed", "false");
    expect(screen.getByTestId("chart")).toHaveTextContent("1 minute:4");
  });

  it("shows a skeleton while the first read is on its way", () => {
    vi.mocked(apiFetch).mockImplementation(() => new Promise(() => {}));
    const { container } = render(<LoadCard {...PROPS} />);
    expect(container.querySelector("[data-slot=skeleton]")).toBeInTheDocument();
    expect(screen.queryByTestId("chart")).not.toBeInTheDocument();
  });
});
