import { fleetCounts } from "@/lib/metrics";
import type { Server } from "@/lib/servers";

/** How many servers there are in each monitoring state: every count is a number with its label. */
export function FleetSummary({ servers }: { servers: Server[] }) {
  const counts = fleetCounts(servers);
  const tiles = [
    { label: "Servers", value: counts.total },
    { label: "Reachable", value: counts.reachable },
    { label: "Unreachable", value: counts.unreachable },
    { label: "Not monitored", value: counts.notMonitored },
    { label: "Not checked yet", value: counts.notChecked },
  ];
  return (
    <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
      {tiles.map(({ label, value }) => (
        <div key={label} className="flex flex-col-reverse gap-1 rounded-xl border bg-card px-4 py-3">
          <dt className="text-sm text-muted-foreground">{label}</dt>
          <dd className="text-2xl font-semibold tabular-nums">{value}</dd>
        </div>
      ))}
    </dl>
  );
}
