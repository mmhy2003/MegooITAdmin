"use client";

import { useState } from "react";
import { LiveBadge } from "@/components/metrics/live-badge";
import { CpuCard } from "@/components/servers/performance/cpu-card";
import { DiskIoCard } from "@/components/servers/performance/disk-io-card";
import { FilesystemsCard } from "@/components/servers/performance/filesystems-card";
import { LoadCard } from "@/components/servers/performance/load-card";
import { MemoryCard } from "@/components/servers/performance/memory-card";
import { NetworkCard } from "@/components/servers/performance/network-card";
import { RangePicker } from "@/components/servers/performance/range-picker";
import { useLiveMetrics } from "@/hooks/use-live-metrics";
import type { RangeName, SampleMessage } from "@/lib/metrics";
import type { Server } from "@/lib/servers";

type Props = { server: Server; range: RangeName; onRange: (range: RangeName) => void };

/**
 * A Linux server's charts over the chosen range. The tab keeps one socket open on every range, so going back to Live
 * needs no new connection; its samples reach the cards only on Live, and each (re)open makes every card read again.
 */
export function PerformanceTab({ server, range, onRange }: Props) {
  const [sample, setSample] = useState<SampleMessage | null>(null);
  const [refill, setRefill] = useState(0);
  const status = useLiveMetrics({
    view: "full",
    serverIds: [server.id],
    onMessage: (m) => {
      if (m.type === "sample") setSample(m);
    },
    onOpen: () => setRefill((n) => n + 1),
  });
  const props = {
    serverId: server.id,
    range,
    sample: range === "live" ? sample : null,
    refill,
    interval: server.metrics_interval_seconds,
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <RangePicker range={range} onChange={onRange} />
        {range === "live" && <LiveBadge status={status} />}
      </div>
      <div className="grid gap-6 md:grid-cols-2">
        <CpuCard {...props} />
        <MemoryCard {...props} />
        <LoadCard {...props} />
        <NetworkCard {...props} />
        <DiskIoCard {...props} />
        <FilesystemsCard {...props} />
      </div>
    </div>
  );
}

export default PerformanceTab;
