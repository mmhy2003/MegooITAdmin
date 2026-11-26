"use client";

import { MetricChart } from "@/components/servers/performance/metric-chart";
import {
  hasNoPoints,
  lineSeries,
  MetricCard,
  type PerformanceCardProps,
  stepMsOf,
} from "@/components/servers/performance/metric-card";
import { useSeries } from "@/components/servers/performance/use-series";
import { formatBytes, lastValue, seriesOf } from "@/lib/metrics";

const METRICS = ["mem.used_bytes", "swap.used_bytes", "mem.total_bytes", "swap.total_bytes"];

/** Memory and swap used over the range, of the newest memory total. */
export function MemoryCard({ serverId, range, sample, refill, interval }: PerformanceCardProps) {
  const state = useSeries(serverId, METRICS, range, sample, refill);
  const { answer } = state;
  const lines = [
    { key: "mem", label: "Memory used", color: "var(--chart-1)", series: lineSeries(answer, "mem.used_bytes"), band: true },
    { key: "swap", label: "Swap used", color: "var(--chart-2)", series: lineSeries(answer, "swap.used_bytes"), band: true },
  ];
  return (
    <MetricCard title="Memory" state={state} empty={hasNoPoints(answer)}>
      <p className="text-sm text-muted-foreground">of {formatBytes(lastValue(seriesOf(answer, "mem.total_bytes")))}</p>
      <MetricChart
        lines={lines}
        stepMs={stepMsOf(answer, interval)}
        unit="bytes"
        label="Memory and swap used"
        dimmed={state.loading}
      />
    </MetricCard>
  );
}
