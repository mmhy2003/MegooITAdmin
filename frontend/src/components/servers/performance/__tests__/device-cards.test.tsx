import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DiskIoCard } from "@/components/servers/performance/disk-io-card";
import { FilesystemsCard } from "@/components/servers/performance/filesystems-card";
import { NetworkCard } from "@/components/servers/performance/network-card";
import { useRefresh } from "@/hooks/use-refresh";
import { ApiError, apiFetch } from "@/lib/api";
import type { ChartLine, RangeName, Series, SeriesAnswer } from "@/lib/metrics";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), apiFetch: vi.fn() }));
vi.mock("@/lib/auth/navigate");
vi.mock("@/hooks/use-refresh", () => ({ useRefresh: vi.fn() }));
vi.mock("@/components/servers/performance/metric-chart", () => ({
  MetricChart: (p: { lines: ChartLine[]; unit: string }) => (
    <div data-testid="chart" data-bands={p.lines.map((l) => l.band).join(",")} data-unit={p.unit}>
      {p.lines.map((l) => `${l.label}:${l.series.time.length}:${l.series.avg.at(-1) ?? "-"}`).join(",")}
    </div>
  ),
}));

const T0 = "2026-11-26T10:00:00Z";
const GIB = 1024 ** 3;

/** A series whose points start at T0 plus `offset` steps of five seconds. */
function series(metric: string, instance: string, values: number[], offset = 0): Series {
  return {
    metric,
    instance,
    time: values.map((_, i) => new Date(Date.parse(T0) + (i + offset) * 5_000).toISOString()),
    avg: values,
    min: values.map((v) => v - 1),
    max: values.map((v) => v + 1),
  };
}

function answer(range: RangeName, list: Series[]): SeriesAnswer {
  return { range, step_seconds: range === "live" ? null : 60, start: T0, end: T0, series: list };
}

const PROPS = { serverId: "s1", range: "live" as RangeName, sample: null, refill: 0, interval: 5 };

function mockReads(list: Series[]) {
  vi.mocked(apiFetch).mockImplementation(async (path: string) => {
    const range = new URLSearchParams(path.split("?")[1]).get("range") as RangeName;
    return answer(range, list);
  });
}

async function choose(select: string, option: string) {
  await userEvent.click(screen.getByRole("combobox", { name: select }));
  await userEvent.click(await screen.findByRole("option", { name: option }));
}

beforeEach(() => {
  vi.mocked(apiFetch).mockReset();
  vi.mocked(useRefresh).mockReset();
});

// eth1 has one point more than eth0, later, so the sum has three times.
const NETWORK = [
  series("net.rx_bytes_per_sec", "eth0", [100, 200]),
  series("net.rx_bytes_per_sec", "eth1", [10, 20], 1),
  series("net.tx_bytes_per_sec", "eth0", [50, 60]),
  series("net.tx_bytes_per_sec", "eth1", [5, 6], 1),
];

describe("NetworkCard", () => {
  it("sums every interface without a band by default", async () => {
    mockReads(NETWORK);
    render(<NetworkCard {...PROPS} />);
    const chart = await screen.findByTestId("chart");
    expect(chart).toHaveTextContent("Received:3:20,Sent:3:6");
    expect(chart).toHaveAttribute("data-bands", "false,false");
    expect(chart).toHaveAttribute("data-unit", "rate");
    expect(screen.getByRole("combobox", { name: "Interface" })).toHaveTextContent("All interfaces");
    expect(apiFetch).toHaveBeenCalledWith(
      "/servers/s1/metrics?range=live&metric=net.rx_bytes_per_sec&metric=net.tx_bytes_per_sec",
      { background: false },
    );
  });

  it("draws one interface's own series with its band", async () => {
    mockReads(NETWORK);
    render(<NetworkCard {...PROPS} />);
    await screen.findByTestId("chart");
    await choose("Interface", "eth0");
    const chart = screen.getByTestId("chart");
    expect(chart).toHaveTextContent("Received:2:200,Sent:2:60");
    expect(chart).toHaveAttribute("data-bands", "true,true");
  });

  it("says there is no data in a range without points", async () => {
    mockReads([series("net.rx_bytes_per_sec", "eth0", [])]);
    render(<NetworkCard {...PROPS} />);
    expect(await screen.findByText("No data in this range")).toBeInTheDocument();
  });

  it("offers to try again after a failed read", async () => {
    vi.mocked(apiFetch).mockRejectedValueOnce(new ApiError(500, "error"));
    render(<NetworkCard {...PROPS} />);
    expect(await screen.findByText("Could not read this chart.")).toBeInTheDocument();
    mockReads(NETWORK);
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByTestId("chart")).toHaveTextContent("Received:3");
  });
});

const DISKIO = [
  series("diskio.read_bytes_per_sec", "sda", [1000, 2000]),
  series("diskio.read_bytes_per_sec", "sdb", [10, 20]),
  series("diskio.write_bytes_per_sec", "sda", [300, 400]),
  series("diskio.write_bytes_per_sec", "sdb", [3, 4]),
  series("diskio.busy_percent", "sda", [12, 25]),
  series("diskio.busy_percent", "sdb", [70, 41]),
];

describe("DiskIoCard", () => {
  it("sums every disk and shows the busiest disk's busy share", async () => {
    mockReads(DISKIO);
    render(<DiskIoCard {...PROPS} />);
    const chart = await screen.findByTestId("chart");
    expect(chart).toHaveTextContent("Read:2:2020,Written:2:404");
    expect(chart).toHaveAttribute("data-bands", "false,false");
    expect(screen.getByRole("combobox", { name: "Disk" })).toHaveTextContent("All disks");
    expect(screen.getByText("Busiest disk busy").nextElementSibling).toHaveTextContent("41%");
  });

  it("draws one disk with its band and its busy share", async () => {
    mockReads(DISKIO);
    render(<DiskIoCard {...PROPS} />);
    await screen.findByTestId("chart");
    await choose("Disk", "sda");
    const chart = screen.getByTestId("chart");
    expect(chart).toHaveTextContent("Read:2:2000,Written:2:400");
    expect(chart).toHaveAttribute("data-bands", "true,true");
    expect(screen.getByText("Busy").nextElementSibling).toHaveTextContent("25%");
    expect(screen.queryByText("Busiest disk busy")).not.toBeInTheDocument();
  });

  it("says there is no data in a range without points", async () => {
    mockReads([]);
    render(<DiskIoCard {...PROPS} />);
    expect(await screen.findByText("No data in this range")).toBeInTheDocument();
  });

  it("offers to try again after a failed read", async () => {
    vi.mocked(apiFetch).mockRejectedValueOnce(new ApiError(500, "error"));
    render(<DiskIoCard {...PROPS} />);
    expect(await screen.findByText("Could not read this chart.")).toBeInTheDocument();
    mockReads(DISKIO);
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByTestId("chart")).toHaveTextContent("Read:2");
  });
});

function filesystems(rootUsed: number, varUsed: number): Series[] {
  return [
    series("disk.used_percent", "/", [40, rootUsed]),
    series("disk.used_percent", "/var", [90, varUsed]),
    series("disk.inodes_used_percent", "/", [5, 6]),
    series("disk.inodes_used_percent", "/var", [20, 30]),
    series("disk.used_bytes", "/", [40 * GIB, 50 * GIB]),
    series("disk.used_bytes", "/var", [9 * GIB, 9.1 * GIB]),
    series("disk.total_bytes", "/", [100 * GIB, 100 * GIB]),
    series("disk.total_bytes", "/var", [10 * GIB, 10 * GIB]),
  ];
}

describe("FilesystemsCard", () => {
  it("starts on the fullest filesystem", async () => {
    mockReads(filesystems(50, 91));
    render(<FilesystemsCard {...PROPS} />);
    const chart = await screen.findByTestId("chart");
    expect(chart).toHaveTextContent("Space used:2:91,Inodes used:2:30");
    expect(chart).toHaveAttribute("data-bands", "true,true");
    expect(chart).toHaveAttribute("data-unit", "percent");
    expect(screen.getByRole("combobox", { name: "Filesystem" })).toHaveTextContent("/var");
  });

  it("lists every filesystem, fullest first, with its warning", async () => {
    mockReads(filesystems(50, 91));
    render(<FilesystemsCard {...PROPS} />);
    const table = await screen.findByRole("table");
    const rows = within(table).getAllByRole("row");
    expect(rows.map((r) => within(r).queryAllByRole("columnheader").map((h) => h.textContent))[0]).toEqual([
      "Mount",
      "Used",
      "Size",
      "Inodes",
    ]);
    expect(rows[1]).toHaveTextContent("/var");
    expect(rows[1]).toHaveTextContent("91% ▲very high");
    expect(rows[1]).toHaveTextContent("9.1 GiB of 10 GiB");
    expect(rows[1]).toHaveTextContent("30%");
    expect(rows[2]).toHaveTextContent("/");
    expect(rows[2]).toHaveTextContent("50 GiB of 100 GiB");
    expect(rows[2]).not.toHaveTextContent("▲");
  });

  it("draws the filesystem chosen in the select", async () => {
    mockReads(filesystems(50, 91));
    render(<FilesystemsCard {...PROPS} />);
    await screen.findByTestId("chart");
    await choose("Filesystem", "/");
    expect(screen.getByTestId("chart")).toHaveTextContent("Space used:2:50,Inodes used:2:6");
  });

  it("keeps the selection when a later answer has another fullest", async () => {
    mockReads(filesystems(50, 91));
    const { rerender } = render(<FilesystemsCard {...PROPS} />);
    expect(await screen.findByTestId("chart")).toHaveTextContent("Space used:2:91");
    mockReads(filesystems(95, 60));
    rerender(<FilesystemsCard {...PROPS} range="6h" />);
    expect(await screen.findByText(/Space used:2:60/)).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Filesystem" })).toHaveTextContent("/var");
  });

  it("says there is no data in a range without points", async () => {
    mockReads([series("disk.used_percent", "/", [])]);
    render(<FilesystemsCard {...PROPS} />);
    expect(await screen.findByText("No data in this range")).toBeInTheDocument();
  });

  it("offers to try again after a failed read", async () => {
    vi.mocked(apiFetch).mockRejectedValueOnce(new ApiError(500, "error"));
    render(<FilesystemsCard {...PROPS} />);
    expect(await screen.findByText("Could not read this chart.")).toBeInTheDocument();
    mockReads(filesystems(50, 91));
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByTestId("chart")).toHaveTextContent("Space used:2:91");
  });
});
