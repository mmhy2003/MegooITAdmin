"use client";

import { Sparkline } from "@/components/metrics/sparkline";
import { MetricChart } from "@/components/servers/performance/metric-chart";
import {
  hasNoPoints,
  lineSeries,
  MetricCard,
  type PerformanceCardProps,
  stepMsOf,
} from "@/components/servers/performance/metric-card";
import { useSeries } from "@/components/servers/performance/use-series";
import { Field } from "@/components/servers/field";
import { formatPercent, instancesOf, lastValue, seriesOf } from "@/lib/metrics";

const METRICS = [
  "cpu.used_percent",
  "cpu.user_percent",
  "cpu.system_percent",
  "cpu.iowait_percent",
  "cpu.steal_percent",
];
const PARTS = [
  ["User", "cpu.user_percent"],
  ["System", "cpu.system_percent"],
  ["I/O wait", "cpu.iowait_percent"],
  ["Steal", "cpu.steal_percent"],
] as const;

/** CPU used over the range, the newest user, system, I/O wait and steal shares, and a small line per core. */
export function CpuCard({ serverId, range, sample, refill, interval }: PerformanceCardProps) {
  const state = useSeries(serverId, METRICS, range, sample, refill);
  const { answer } = state;
  const lines = [
    { key: "used", label: "CPU used", color: "var(--chart-1)", series: lineSeries(answer, "cpu.used_percent"), band: true },
  ];
  return (
    <MetricCard title="CPU" state={state} empty={hasNoPoints(answer)}>
      <MetricChart
        lines={lines}
        stepMs={stepMsOf(answer, interval)}
        unit="percent"
        label="CPU used"
        dimmed={state.loading}
      />
      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {PARTS.map(([label, metric]) => (
          <Field key={metric} label={label}>
            <span className="font-mono tabular-nums">{formatPercent(lastValue(seriesOf(answer, metric)))}</span>
          </Field>
        ))}
      </dl>
      <ul className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs sm:grid-cols-4">
        {instancesOf(answer, "cpu.used_percent").map((core) => (
          <li key={core} className="flex items-center gap-2">
            <span className="w-10 font-mono text-muted-foreground">{core}</span>
            <Sparkline values={lineSeries(answer, "cpu.used_percent", core).avg} label={`${core}, CPU used`} />
          </li>
        ))}
      </ul>
    </MetricCard>
  );
}
