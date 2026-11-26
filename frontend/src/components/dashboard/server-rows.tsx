import Link from "next/link";
import { PercentValue } from "@/components/metrics/percent-value";
import { MonitoringBadge } from "@/components/servers/monitoring-badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatLoad, formatRate, isStale, type Vitals } from "@/lib/metrics";
import type { Server } from "@/lib/servers";
import { cn } from "@/lib/utils";

const DASH = "—";

type Props = {
  servers: Server[];
  vitalsOf: Record<string, Vitals>;
  now: number;
  track: (element: Element | null) => void;
};

/** The Dashboard as a table: one row per server with its newest numbers, dashes when it is not monitored. */
export function ServerRows({ servers, vitalsOf, now, track }: Props) {
  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Name</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>CPU</TableHead>
            <TableHead>Memory</TableHead>
            <TableHead>Disk</TableHead>
            <TableHead>Load</TableHead>
            <TableHead>Network</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {servers.map((server) => {
            const state = server.monitoring?.state;
            const vitals = vitalsOf[server.id];
            const live = state === "reachable" || state === "unreachable";
            const overview = live && !isStale(vitals?.overview.time ?? null, now) ? vitals?.overview : undefined;
            return (
              <TableRow
                key={server.id}
                ref={track}
                data-server-id={server.id}
                className={cn(state === "unreachable" && "opacity-60")}
              >
                <TableCell className="font-medium">
                  <Link href={`/servers/${server.id}`} className="hover:underline">
                    {server.name}
                  </Link>
                </TableCell>
                <TableCell>
                  <MonitoringBadge monitoring={server.monitoring} />
                </TableCell>
                <TableCell className="tabular-nums">
                  <PercentValue value={overview?.cpu ?? null} />
                </TableCell>
                <TableCell className="tabular-nums">
                  <PercentValue value={overview?.mem ?? null} />
                </TableCell>
                <TableCell className="tabular-nums">
                  {overview?.disk ? (
                    <span className="flex items-center gap-2">
                      <span className="font-mono text-xs">{overview.disk.mount}</span>
                      <PercentValue value={overview.disk.percent} />
                    </span>
                  ) : (
                    DASH
                  )}
                </TableCell>
                <TableCell className="tabular-nums">{formatLoad(overview?.load ?? null)}</TableCell>
                <TableCell className="tabular-nums">
                  {overview ? (
                    <span>
                      <span aria-hidden>↓ </span>
                      {formatRate(overview.rx)}
                      <span className="sr-only"> received</span>
                      <span aria-hidden> ↑ </span>
                      {formatRate(overview.tx)}
                      <span className="sr-only"> sent</span>
                    </span>
                  ) : (
                    DASH
                  )}
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}
