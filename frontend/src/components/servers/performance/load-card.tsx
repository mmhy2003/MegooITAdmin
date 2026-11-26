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

const METRICS = ["load.1m", "load.5m", "load.15m"];

/** The 1, 5 and 15 minute load averages over the range. */
export function LoadCard({ serverId, range, sample, refill, interval }: PerformanceCardProps) {
  const state = useSeries(serverId, METRICS, range, sample, refill);
  const { answer } = state;
  const lines = [
    { key: "m1", label: "1 minute", color: "var(--chart-1)", series: lineSeries(answer, "load.1m"), band: true },
    { key: "m5", label: "5 minutes", color: "var(--chart-2)", series: lineSeries(answer, "load.5m"), band: true },
    { key: "m15", label: "15 minutes", color: "var(--chart-3)", series: lineSeries(answer, "load.15m"), band: true },
  ];
  return (
    <MetricCard title="Load" state={state} empty={hasNoPoints(answer)}>
      <MetricChart lines={lines} stepMs={stepMsOf(answer, interval)} unit="load" label="Load" dimmed={state.loading} />
    </MetricCard>
  );
}
