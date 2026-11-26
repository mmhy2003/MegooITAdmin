"use client";

import { useState } from "react";
import { PercentValue } from "@/components/metrics/percent-value";
import { MetricChart } from "@/components/servers/performance/metric-chart";
import {
  DeviceSelect,
  hasNoPoints,
  lineSeries,
  MetricCard,
  type PerformanceCardProps,
  stepMsOf,
} from "@/components/servers/performance/metric-card";
import { useSeries } from "@/components/servers/performance/use-series";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatBytes, instancesOf, lastValue, type SeriesAnswer, seriesOf } from "@/lib/metrics";

const USED = "disk.used_percent";
const INODES = "disk.inodes_used_percent";
const USED_BYTES = "disk.used_bytes";
const TOTAL_BYTES = "disk.total_bytes";
const METRICS = [USED, INODES, USED_BYTES, TOTAL_BYTES];

type Filesystem = { mount: string; used: number | null; inodes: number | null; usedBytes: number | null; total: number | null };

/** The newest numbers of every filesystem, fullest first. */
function filesystemsOf(answer: SeriesAnswer | null): Filesystem[] {
  return instancesOf(answer, USED)
    .map((mount) => ({
      mount,
      used: lastValue(seriesOf(answer, USED, mount)),
      inodes: lastValue(seriesOf(answer, INODES, mount)),
      usedBytes: lastValue(seriesOf(answer, USED_BYTES, mount)),
      total: lastValue(seriesOf(answer, TOTAL_BYTES, mount)),
    }))
    .sort((a, b) => (b.used ?? -1) - (a.used ?? -1));
}

/** Space and inodes used of one filesystem over the range, starting on the fullest, and a table of all of them. */
export function FilesystemsCard({ serverId, range, sample, refill, interval }: PerformanceCardProps) {
  const state = useSeries(serverId, METRICS, range, sample, refill);
  const { answer } = state;
  const all = filesystemsOf(answer);
  // The fullest is chosen once, when the first answer with a filesystem arrives; later answers keep the choice.
  const [chosen, setChosen] = useState<string | null>(null);
  if (chosen === null && all.length > 0) setChosen(all[0].mount);
  const mount = chosen ?? "";

  const lines = [
    { key: "used", label: "Space used", color: "var(--chart-1)", series: lineSeries(answer, USED, mount), band: true },
    { key: "inodes", label: "Inodes used", color: "var(--chart-2)", series: lineSeries(answer, INODES, mount), band: true },
  ];
  const select = (
    <DeviceSelect label="Filesystem" value={mount} devices={instancesOf(answer, USED)} onChange={setChosen} />
  );
  return (
    <MetricCard title="Filesystems" state={state} empty={hasNoPoints(answer)} action={select}>
      <MetricChart
        lines={lines}
        stepMs={stepMsOf(answer, interval)}
        unit="percent"
        label={`Space and inodes used of ${mount}`}
        dimmed={state.loading}
      />
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Mount</TableHead>
            <TableHead>Used</TableHead>
            <TableHead>Size</TableHead>
            <TableHead>Inodes</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {all.map((fs) => (
            <TableRow key={fs.mount}>
              <TableCell className="font-mono">{fs.mount}</TableCell>
              <TableCell>
                <PercentValue value={fs.used} />
              </TableCell>
              <TableCell className="tabular-nums">
                {formatBytes(fs.usedBytes)} of {formatBytes(fs.total)}
              </TableCell>
              <TableCell>
                <PercentValue value={fs.inodes} />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </MetricCard>
  );
}
