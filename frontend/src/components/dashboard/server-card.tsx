import Link from "next/link";
import { ServerVitals } from "@/components/metrics/server-vitals";
import { MonitoringBadge } from "@/components/servers/monitoring-badge";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { monitoringText, NOT_CHECKED } from "@/lib/auth/messages";
import { isStale, type Vitals } from "@/lib/metrics";
import type { Server } from "@/lib/servers";

type Props = {
  server: Server;
  vitals: Vitals | undefined;
  now: number;
  track: (element: Element | null) => void;
  /** How many alerts fire on the server. */
  alerts?: number;
};

/** "1 alert" or "N alerts" firing on a server, or nothing when none fires. */
export function AlertCount({ alerts = 0 }: { alerts?: number }) {
  if (alerts === 0) return null;
  return <Badge variant="destructive">{alerts === 1 ? "1 alert" : `${alerts} alerts`}</Badge>;
}

function Note({ children }: { children: string | undefined }) {
  return children ? <p className="text-sm text-muted-foreground">{children}</p> : null;
}

function Body({ server, vitals, now }: Omit<Props, "track" | "alerts">) {
  const monitoring = server.monitoring;
  if (monitoring === null) return <Note>{NOT_CHECKED.title}</Note>;
  const stale = isStale(vitals?.overview.time ?? null, now);
  if (monitoring.state === "reachable") return <ServerVitals vitals={vitals} stale={stale} />;
  const reason = monitoringText(monitoring.reason)?.title;
  if (monitoring.state === "unreachable")
    return (
      <div className="space-y-3">
        <Note>{reason}</Note>
        <div className="opacity-60">
          <ServerVitals vitals={vitals} stale={stale} />
        </div>
      </div>
    );
  if (server.os === "windows") return <Note>Windows servers are not monitored yet.</Note>;
  return (
    <div className="space-y-1">
      <p className="text-sm font-medium">Not monitored</p>
      <Note>{reason}</Note>
    </div>
  );
}

/** One server on the Dashboard: its name, its state, its firing alerts and its newest numbers. */
export function ServerCard({ server, vitals, now, track, alerts }: Props) {
  return (
    <Card ref={track} data-server-id={server.id}>
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2">
          <Link href={`/servers/${server.id}`} className="hover:underline">
            {server.name}
          </Link>
          <MonitoringBadge monitoring={server.monitoring} />
          <AlertCount alerts={alerts} />
        </CardTitle>
        <CardDescription>{server.group_name}</CardDescription>
      </CardHeader>
      <CardContent>
        <Body server={server} vitals={vitals} now={now} />
      </CardContent>
    </Card>
  );
}
