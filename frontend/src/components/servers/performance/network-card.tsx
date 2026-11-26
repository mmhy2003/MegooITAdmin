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
import { instancesOf } from "@/lib/metrics";

const RX = "net.rx_bytes_per_sec";
const TX = "net.tx_bytes_per_sec";
const METRICS = [RX, TX];

/** Bytes received and sent per second, by one interface or all of them. A sum has no band: the lows and highs of
 * different interfaces cannot be added. */
export function NetworkCard({ serverId, range, sample, refill, interval }: PerformanceCardProps) {
  const state = useSeries(serverId, METRICS, range, sample, refill);
  const [device, setDevice] = useState(ALL_DEVICES);
  const { answer } = state;
  const band = device !== ALL_DEVICES;
  const lines = [
    { key: "rx", label: "Received", color: "var(--chart-1)", series: deviceSeries(answer, RX, device), band },
    { key: "tx", label: "Sent", color: "var(--chart-2)", series: deviceSeries(answer, TX, device), band },
  ];
  const select = (
    <DeviceSelect
      label="Interface"
      value={device}
      devices={instancesOf(answer, RX)}
      all="All interfaces"
      onChange={setDevice}
    />
  );
  return (
    <MetricCard title="Network" state={state} empty={hasNoPoints(answer)} action={select}>
      <MetricChart
        lines={lines}
        stepMs={stepMsOf(answer, interval)}
        unit="rate"
        label="Network received and sent"
        dimmed={state.loading}
      />
    </MetricCard>
  );
}
