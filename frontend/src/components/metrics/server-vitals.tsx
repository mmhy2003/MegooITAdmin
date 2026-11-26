import type { ReactNode } from "react";
import { Meter } from "@/components/metrics/meter";
import { PercentValue } from "@/components/metrics/percent-value";
import { Sparkline } from "@/components/metrics/sparkline";
import { formatLoad, formatRate, type Vitals } from "@/lib/metrics";
import { cn } from "@/lib/utils";

const DASH = "—";

function Item({ label, children, strip }: { label: string; children: ReactNode; strip: boolean }) {
  return (
    <div className={cn(strip ? "flex min-w-0 flex-col gap-1" : "col-span-2 grid grid-cols-subgrid items-center")}>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="flex min-w-0 items-center gap-2 tabular-nums">{children}</dd>
    </div>
  );
}

/** The newest numbers of a server, as rows of a card or as one strip; everything is a dash when stale or missing. */
export function ServerVitals({
  vitals,
  stale,
  layout = "rows",
}: {
  vitals: Vitals | undefined;
  stale: boolean;
  layout?: "rows" | "strip";
}) {
  const shown = stale ? undefined : vitals;
  const overview = shown?.overview;
  const strip = layout === "strip";
  const disk = overview?.disk ?? null;
  return (
    <dl className={cn(strip ? "flex flex-wrap gap-6" : "grid grid-cols-[auto_1fr] gap-x-3 gap-y-2", "text-sm")}>
      <Item label="CPU" strip={strip}>
        <PercentValue value={overview?.cpu ?? null} />
        {overview && <Meter percent={overview.cpu} />}
        {shown && <Sparkline values={shown.trend.cpu} label="CPU, last 5 minutes" className="shrink-0" />}
      </Item>
      <Item label="Memory" strip={strip}>
        <PercentValue value={overview?.mem ?? null} />
        {overview && <Meter percent={overview.mem} />}
        {shown && <Sparkline values={shown.trend.mem} label="Memory, last 5 minutes" className="shrink-0" />}
      </Item>
      <Item label="Fullest filesystem" strip={strip}>
        {disk ? (
          <>
            <span className="truncate font-mono text-xs">{disk.mount}</span>
            <PercentValue value={disk.percent} />
            <Meter percent={disk.percent} />
          </>
        ) : (
          DASH
        )}
      </Item>
      <Item label="Load" strip={strip}>
        {formatLoad(overview?.load ?? null)}
      </Item>
      <Item label="Network" strip={strip}>
        <span>
          <span aria-hidden>↓ </span>
          {formatRate(overview?.rx ?? null)}
          <span className="sr-only"> received</span>
          <span aria-hidden> ↑ </span>
          {formatRate(overview?.tx ?? null)}
          <span className="sr-only"> sent</span>
        </span>
      </Item>
    </dl>
  );
}
