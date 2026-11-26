"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { LiveBadge } from "@/components/metrics/live-badge";
import { ServerVitals } from "@/components/metrics/server-vitals";
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useLiveMetrics } from "@/hooks/use-live-metrics";
import { useRefresh } from "@/hooks/use-refresh";
import { apiFetch } from "@/lib/api";
import { applyMessage, isStale, vitalsOf, type LiveMessage, type OverviewRead, type Vitals } from "@/lib/metrics";
import type { Server } from "@/lib/servers";
import { cn } from "@/lib/utils";

/** The strip turns to dashes when its newest values grow stale, so it looks at the clock this often. */
const TICK_MS = 5_000;

function timeOf(vitals: Vitals | undefined): number {
  const time = vitals?.overview.time;
  return time ? Date.parse(time) : -Infinity;
}

/** The newer of two vitals; a read never replaces newer live values. */
function newer(previous: Vitals | undefined, next: Vitals): Vitals {
  return previous !== undefined && timeOf(previous) > timeOf(next) ? previous : next;
}

/** A Linux server's newest CPU, memory, disk, load and network on its Overview, kept live by its own socket. */
export function LiveStrip({ server }: { server: Server }) {
  const [vitals, setVitals] = useState<Vitals | undefined>(undefined);
  const [now, setNow] = useState(() => Date.now());

  const read = useCallback(
    (background: boolean) => {
      apiFetch<OverviewRead>(`/metrics/overview?server_id=${server.id}`, { background }).then(
        (answer) => {
          const found = answer.servers[0];
          if (found) setVitals((previous) => newer(previous, vitalsOf(found)));
        },
        () => {},
      );
    },
    [server.id],
  );

  useEffect(() => {
    read(false);
  }, [read]);

  useRefresh(
    useCallback(() => read(true), [read]),
    true,
  );

  const status = useLiveMetrics({
    view: "overview",
    serverIds: [server.id],
    onMessage: (m: LiveMessage) => {
      if (m.type === "overview" && m.server_id === server.id) setVitals((v) => applyMessage(v, m));
    },
    onOpen: () => read(true),
  });

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), TICK_MS);
    return () => clearInterval(timer);
  }, []);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2">
          <h3>Live</h3>
          <LiveBadge status={status} />
        </CardTitle>
        <CardAction>
          <Link
            href={`/servers/${server.id}?tab=performance`}
            className="text-sm text-primary underline-offset-4 hover:underline"
          >
            Performance
          </Link>
        </CardAction>
      </CardHeader>
      <CardContent className={cn(server.monitoring?.state === "unreachable" && "opacity-60")}>
        <ServerVitals vitals={vitals} stale={isStale(vitals?.overview.time ?? null, now)} layout="strip" />
      </CardContent>
    </Card>
  );
}
