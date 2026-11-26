"use client";

import { useState } from "react";
import { MetricChart } from "@/components/servers/performance/metric-chart";
import {
  ALL_DEVICES,
  DeviceSelect,
  deviceSeries,
  hasNoPoints,
  MetricCard,
  type PerformanceCardProps,
  stepMsOf,
} from "@/components/servers/performance/metric-card";
import { useSeries } from "@/components/servers/performance/use-series";
import { Field } from "@/components/servers/field";
import { formatPercent, instancesOf, lastValue, type SeriesAnswer, seriesOf } from "@/lib/metrics";

const READ = "diskio.read_bytes_per_sec";
const WRITE = "diskio.write_bytes_per_sec";
const BUSY = "diskio.busy_percent";
const METRICS = [READ, WRITE, BUSY];

/** The newest busy share of one disk, or the highest of every disk. */
function busyOf(answer: SeriesAnswer | null, device: string): number | null {
  if (device !== ALL_DEVICES) return lastValue(seriesOf(answer, BUSY, device));
  const values = instancesOf(answer, BUSY)
    .map((disk) => lastValue(seriesOf(answer, BUSY, disk)))
    .filter((v) => v !== null);
  return values.length === 0 ? null : Math.max(...values);
}

/** Bytes read and written per second by one disk or all of them, and how busy it is. A sum has no band: the lows
 * and highs of different disks cannot be added. */
export function DiskIoCard({ serverId, range, sample, refill, interval }: PerformanceCardProps) {
  const state = useSeries(serverId, METRICS, range, sample, refill);
  const [device, setDevice] = useState(ALL_DEVICES);
  const { answer } = state;
  const band = device !== ALL_DEVICES;
  const lines = [
    { key: "read", label: "Read", color: "var(--chart-1)", series: deviceSeries(answer, READ, device), band },
    { key: "write", label: "Written", color: "var(--chart-2)", series: deviceSeries(answer, WRITE, device), band },
  ];
  const select = (
    <DeviceSelect label="Disk" value={device} devices={instancesOf(answer, READ)} all="All disks" onChange={setDevice} />
  );
  return (
    <MetricCard title="Disk I/O" state={state} empty={hasNoPoints(answer)} action={select}>
      <MetricChart
        lines={lines}
        stepMs={stepMsOf(answer, interval)}
        unit="rate"
        label="Disk read and written"
        dimmed={state.loading}
      />
      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Field label={band ? "Busy" : "Busiest disk busy"}>
          <span className="font-mono tabular-nums">{formatPercent(busyOf(answer, device))}</span>
        </Field>
      </dl>
    </MetricCard>
  );
}
